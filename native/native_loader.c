/* Derived from OMGrant/ft9201-libfprint, commit fcf5499c6ddadf0d2a03be14b173609e760a7ec6.
 * LGPL-2.1-or-later. See LICENSE and NOTICE.md. Fixed-DLL offline research only. */
// loader.c — native in-process loader for ftWbioEngineAdapter.dll, NO WINE.
// Maps the PE, sets up a fake x64 TEB in %gs, runs static-CRT DllMain, then
// calls WbioQueryEngineInterface + Attach + AcceptSampleData on a real print.
//
// Build: gcc -O0 -g -o loader loader.c
// x86-64 Linux: glibc TLS uses %fs, so %gs is free for the Windows TEB.

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdarg.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <asm/prctl.h>
#include <sys/stat.h>
#include <errno.h>
#include <time.h>
#include <pthread.h>
#include <openssl/evp.h>

typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
#define MS __attribute__((ms_abi))
#define DLL_PROCESS_ATTACH 1

static u8 *g_image;          // mapped image base
static u64 g_imagebase;      // preferred base 0x180000000
static const char *g_dllpath;

// ---------- tiny PE structures (only fields we use) ----------
#pragma pack(push,1)
typedef struct { u16 e_magic; u8 pad[58]; u32 e_lfanew; } DOS;
typedef struct {
  u32 Signature; u16 Machine, NumSecs; u32 TimeStamp, PtrSym, NumSym; u16 OptSize, Chars;
} FILEHDR;
typedef struct { u8 Name[8]; u32 VSize, VAddr, RawSize, RawPtr; u32 pad[3]; u16 pad2[2]; u32 Chars; } SEC;
#pragma pack(pop)

static u8 *g_file; static long g_filelen;
static u32 f32(u64 o){ return *(u32*)(g_file+o); }
static u64 f64(u64 o){ return *(u64*)(g_file+o); }
static u16 f16(u64 o){ return *(u16*)(g_file+o); }

// ---------- fake TEB / gs ----------
static u8 g_teb[0x2000];
static u8 g_peb[0x1000];
static void *g_tls_array[64];
static u8  g_tls_block[0x2000];

static int set_gs(void *base){ return syscall(SYS_arch_prctl, ARCH_SET_GS, base); }

// ---------- import shim table ----------
typedef struct { const char *name; void *fn; } Shim;
static Shim shims[128]; static int nshims;
static void reg(const char*n, void*f){ if(nshims>=(int)(sizeof shims/sizeof*shims)){fprintf(stderr,"ft_engine: shim table full (%d) — raise shims[]\n",nshims);abort();} shims[nshims].name=n; shims[nshims].fn=f; nshims++; }
static void* find_shim(const char*n){ for(int i=0;i<nshims;i++) if(!strcmp(shims[i].name,n)) return shims[i].fn; return 0; }

static unsigned imports_resolved,unsupported_calls;
static unsigned trace_count[256]; static const char *trace_name[256]; static unsigned traces;
static unsigned long old_gs;
static void native_trace(const char *name) {
  for(unsigned i=0;i<traces;i++)if(!strcmp(name,trace_name[i])){trace_count[i]++;return;}
  if(traces>=256)_exit(121);trace_name[traces]=name;trace_count[traces++]=1;
}
static __attribute__((noreturn)) void unsupported(const char *name) {
  unsupported_calls++;fprintf(stderr,"unsupported Windows API: %s\n",name);fflush(stderr);_exit(120);
}
// ================= SHIMS (all MS ABI) =================
static u32 g_lasterr=0;
static void MS sh_SetLastError(u32 e){native_trace("sh_SetLastError"); g_lasterr=e; }
static u32  MS sh_GetLastError(void){native_trace("sh_GetLastError"); return g_lasterr; }

typedef struct { u64 size,magic; } HeapHeader;
#define HEAP_MAGIC 0x79616d696c616870ULL
static HeapHeader *heap_header(void *p){HeapHeader*h=(HeapHeader*)p-1;if(h->magic!=HEAP_MAGIC)unsupported("invalid heap pointer");return h;}
static void* MS sh_GetProcessHeap(void){native_trace("sh_GetProcessHeap");return (void*)0x100;}
static void* MS sh_HeapAlloc(void*h,u32 flags,u64 size){native_trace("sh_HeapAlloc");
  if(h!=(void*)0x100 || size>64*1024*1024 || (flags&~8u))unsupported("HeapAlloc flags/size");
  HeapHeader*p=malloc(sizeof(*p)+(size?size:1));if(!p){g_lasterr=8;return 0;}
  p->size=size;p->magic=HEAP_MAGIC;void*out=p+1;if(flags&8)memset(out,0,size);return out;
}
static int MS sh_HeapFree(void*h,u32 flags,void*p){native_trace("sh_HeapFree");if(h!=(void*)0x100||flags)unsupported("HeapFree flags");if(p){HeapHeader*b=heap_header(p);b->magic=0;free(b);}return 1;}
static void* MS sh_HeapReAlloc(void*h,u32 flags,void*p,u64 size){native_trace("sh_HeapReAlloc");
  if(!p)return sh_HeapAlloc(h,flags,size);
  if(h!=(void*)0x100 || (flags&~8u) || size>64*1024*1024)unsupported("HeapReAlloc flags/size");
  HeapHeader*b=heap_header(p);u64 old=b->size;b=realloc(b,sizeof(*b)+(size?size:1));if(!b){g_lasterr=8;return 0;}
  b->size=size;if((flags&8)&&size>old)memset((u8*)(b+1)+old,0,size-old);return b+1;
}
static u64 MS sh_HeapSize(void*h,u32 flags,void*p){native_trace("sh_HeapSize");return heap_header(p)->size;}
static int MS sh_HeapValidate(void*h,u32 flags,void*p){native_trace("sh_HeapValidate");if(p)heap_header(p);return 1;}
static int MS sh_HeapQueryInformation(void*h,int c,void*b,u64 l,u64*r){native_trace("sh_HeapQueryInformation");unsupported("HeapQueryInformation");return 0;}

typedef struct {void*address;pthread_mutex_t mutex;} NativeLock;
static NativeLock locks[256];static unsigned lock_count;
static NativeLock* lock_get(void *p,int create){
  for(unsigned i=0;i<lock_count;i++)if(locks[i].address==p)return &locks[i];
  if(!create||lock_count>=256)unsupported("critical section not initialized");
  NativeLock*l=&locks[lock_count++];l->address=p;pthread_mutexattr_t a;
  pthread_mutexattr_init(&a);pthread_mutexattr_settype(&a,PTHREAD_MUTEX_RECURSIVE);pthread_mutex_init(&l->mutex,&a);pthread_mutexattr_destroy(&a);return l;
}
static void MS sh_InitCS(void*p){native_trace("sh_InitCS");lock_get(p,1);}
static u32 MS sh_InitCSSpin(void*p,u32 spin){native_trace("sh_InitCSSpin");lock_get(p,1);return 1;}
static void MS sh_EnterCS(void*p){native_trace("sh_EnterCS");if(pthread_mutex_lock(&lock_get(p,0)->mutex))unsupported("critical section lock");}
static void MS sh_LeaveCS(void*p){native_trace("sh_LeaveCS");if(pthread_mutex_unlock(&lock_get(p,0)->mutex))unsupported("critical section unlock");}
static void MS sh_DeleteCS(void*p){native_trace("sh_DeleteCS");NativeLock*l=lock_get(p,0);pthread_mutex_destroy(&l->mutex);l->address=0;}
typedef struct{void*address;void*head;} NativeSList;
static NativeSList slists[128];static unsigned slist_count;
static NativeSList* slist_get(void*p,int create){for(unsigned i=0;i<slist_count;i++)if(slists[i].address==p)return &slists[i];if(!create||slist_count>=128)unsupported("unknown SList");NativeSList*l=&slists[slist_count++];l->address=p;l->head=NULL;return l;}
static void MS sh_InitSList(void*p){native_trace("sh_InitSList");memset(p,0,16);slist_get(p,1)->head=NULL;}
static void* MS sh_FlushSList(void*p){native_trace("sh_FlushSList");NativeSList*l=slist_get(p,0);void*head=l->head;l->head=NULL;return head;}

// TLS
static u32 g_tls_next=1; static void* g_tls_vals[1088];
static u32 MS sh_TlsAlloc(void){native_trace("sh_TlsAlloc");if(g_tls_next>=1088)unsupported("TLS slots exhausted");return g_tls_next++;}
static int MS sh_TlsFree(u32 i){native_trace("sh_TlsFree");if(i>=1088)unsupported("TLS index");g_tls_vals[i]=0;return 1;}
static void* MS sh_TlsGetValue(u32 i){native_trace("sh_TlsGetValue"); g_lasterr=0; return i<1088?g_tls_vals[i]:0; }
static int MS sh_TlsSetValue(u32 i,void*v){native_trace("sh_TlsSetValue");if(i>=1088)unsupported("TLS index");g_tls_vals[i]=v;return 1;}

// process/thread/module
static void* MS sh_GetCurrentProcess(void){native_trace("sh_GetCurrentProcess"); return (void*)-1; }
static u32 MS sh_GetCurrentProcessId(void){native_trace("sh_GetCurrentProcessId");return getpid();}
static u32 MS sh_GetCurrentThreadId(void){native_trace("sh_GetCurrentThreadId");return syscall(SYS_gettid);}
static void* MS sh_GetModuleHandleW(void*n){native_trace("sh_GetModuleHandleW"); return (void*)g_image; }
static void* MS sh_GetModuleHandleA(void*n){native_trace("sh_GetModuleHandleA"); return (void*)g_image; }
static int  MS sh_GetModuleHandleExW(u32 f,void*n,void**h){native_trace("sh_GetModuleHandleExW"); if(h)*h=(void*)g_image; return 1; }
static u32  MS sh_GetModuleFileNameA(void*m,char*b,u32 n){native_trace("sh_GetModuleFileNameA"); strncpy(b,g_dllpath,n); return strlen(g_dllpath); }
static u32  MS sh_GetModuleFileNameW(void*m,u16*b,u32 n){native_trace("sh_GetModuleFileNameW"); u32 i=0; for(;g_dllpath[i]&&i<n-1;i++) b[i]=g_dllpath[i]; b[i]=0; return i; }
static void* MS sh_LoadLibraryExW(void*n,void*h,u32 f){
  native_trace("sh_LoadLibraryExW");char name[200]={0};if(!n||h||(f!=0&&f!=0x800))unsupported("LoadLibraryExW arguments");
  for(int i=0;i<199&&((u16*)n)[i];i++){if(((u16*)n)[i]>127)unsupported("LoadLibraryExW non-ASCII");name[i]=((u16*)n)[i];}
  if(!strncmp(name,"api-ms-win-core-",16)||!strcmp(name,"kernel32")||!strcmp(name,"kernel32.dll")||!strcmp(name,"KERNEL32.dll"))return (void*)0x1000;
  fprintf(stderr,"unimplemented module %s\n",name);unsupported("LoadLibraryExW module");
}
static int MS sh_FreeLibrary(void*h){native_trace("sh_FreeLibrary");if(h!=(void*)0x1000)unsupported("FreeLibrary handle");return 1;}
static void* MS sh_GetProcAddress(void*h,const char*n){native_trace("sh_GetProcAddress"); if((u64)n>>16==0) return 0; /*by ordinal*/ return find_shim(n); }

// console/file → route engine logs to stderr so we SEE its [Engine] output
static void* MS sh_GetStdHandle(u32 n){native_trace("sh_GetStdHandle"); return (void*)(u64)(n?n:1); }
static int  MS sh_SetStdHandle(u32 n,void*h){native_trace("sh_SetStdHandle"); return 1; }
static u32  MS sh_GetFileType(void*h){native_trace("sh_GetFileType"); return 2; /*CHAR*/ }
static int  MS sh_GetConsoleMode(void*h,u32*m){native_trace("sh_GetConsoleMode"); if(m)*m=0; return 1; }
static u32  MS sh_GetConsoleCP(void){native_trace("sh_GetConsoleCP"); return 437; }
static int  MS sh_WriteFile(void*h,const void*b,u32 n,u32*wr,void*o){native_trace("sh_WriteFile"); unsupported("WriteFile"); }
static int  MS sh_WriteConsoleW(void*h,const u16*b,u32 n,u32*wr,void*r){native_trace("sh_WriteConsoleW"); unsupported("WriteConsoleW"); }
static void MS sh_OutputDebugStringA(const char*s){native_trace("sh_OutputDebugStringA"); fprintf(stderr,"%s",s?s:""); }
static void MS sh_OutputDebugStringW(const u16*s){native_trace("sh_OutputDebugStringW"); if(s)for(;*s;s++) fputc(*s&0xff,stderr); }
static int  MS sh_FlushFileBuffers(void*h){native_trace("sh_FlushFileBuffers"); return 1; }
static void* MS sh_CreateFileW(void*n,u32 a,u32 s,void*sa,u32 c,u32 fl,void*t){native_trace("sh_CreateFileW"); unsupported("CreateFileW"); } // config absent → graceful
static int  MS sh_SetFilePointerEx(void*h,long long d,void*np,u32 m){native_trace("sh_SetFilePointerEx"); unsupported("SetFilePointerEx"); }
static int  MS sh_CloseHandle(void*h){native_trace("sh_CloseHandle"); unsupported("CloseHandle"); }
static void* MS sh_FindFirstFileExA(void*n,int i,void*d,int o,void*s,u32 f){native_trace("sh_FindFirstFileExA"); unsupported("FindFirstFileExA"); }
static int  MS sh_FindNextFileA(void*h,void*d){native_trace("sh_FindNextFileA"); unsupported("FindNextFileA"); }
static int  MS sh_FindClose(void*h){native_trace("sh_FindClose"); unsupported("FindClose"); }
static u32  MS sh_GetSystemDirectoryA(char*b,u32 n){native_trace("sh_GetSystemDirectoryA"); unsupported("GetSystemDirectoryA"); }

// sync / events → the engine's global lock
static void* MS sh_CreateEventW(void*sa,int man,int init,void*name){native_trace("sh_CreateEventW"); unsupported("CreateEventW"); }
static int  MS sh_SetEvent(void*h){native_trace("sh_SetEvent"); unsupported("SetEvent"); }
static int  MS sh_ResetEvent(void*h){native_trace("sh_ResetEvent"); unsupported("ResetEvent"); }
static u32  MS sh_WaitForSingleObject(void*h,u32 ms){native_trace("sh_WaitForSingleObject"); unsupported("WaitForSingleObject"); }
static u32  MS sh_WaitForSingleObjectEx(void*h,u32 ms,int a){native_trace("sh_WaitForSingleObjectEx"); unsupported("WaitForSingleObjectEx"); }
static void* MS sh_CreateThread(void*sa,u64 st,void*fn,void*arg,u32 fl,u32*id){native_trace("sh_CreateThread"); unsupported("CreateThread"); }
static int MS sh_DeviceIoControl(void*h,u32 c,void*ib,u32 il,void*ob,u32 ol,u32*ret,void*ov){
  native_trace("sh_DeviceIoControl");if(c!=0x00442018||ib||il||!ob||ol!=2||!ret||ov)unsupported("DeviceIoControl outside dimensions query");
  ((u8*)ob)[0]=64;((u8*)ob)[1]=80;*ret=2;return 1;
}

// locale / codepage (ucrt init)
static u32  MS sh_GetACP(void){native_trace("sh_GetACP"); return 1252; }
static u32  MS sh_GetOEMCP(void){native_trace("sh_GetOEMCP"); return 437; }
static int  MS sh_GetCPInfo(u32 cp,void*info){native_trace("sh_GetCPInfo"); if(info){ u8*p=info; *(u32*)p=1; p[4]=0; p[5]=0; } return 1; }
static int  MS sh_IsValidCodePage(u32 cp){native_trace("sh_IsValidCodePage"); return 1; }
static int  MS sh_MultiByteToWideChar(u32 cp,u32 f,const char*mb,int mbc,u16*wc,int wcc){native_trace("sh_MultiByteToWideChar");
  if(mbc<0) mbc=strlen(mb)+1;
  if(wcc==0) return mbc;
  int n=mbc<wcc?mbc:wcc;
  for(int i=0;i<n;i++) wc[i]=(u8)mb[i];
  return n; }
static int  MS sh_WideCharToMultiByte(u32 cp,u32 f,const u16*wc,int wcc,char*mb,int mbc,void*d,void*u){native_trace("sh_WideCharToMultiByte");
  if(wcc<0){ wcc=0; while(wc[wcc]) wcc++; wcc++; } if(mbc==0) return wcc; int n=wcc<mbc?wcc:mbc; for(int i=0;i<n;i++) mb[i]=(char)wc[i]; return n; }
static int  MS sh_LCMapStringW(u32 l,u32 f,const u16*s,int sc,u16*d,int dc){native_trace("sh_LCMapStringW"); if(dc==0) return sc; int n=sc<dc?sc:dc; for(int i=0;i<n;i++) d[i]=s[i]; return n; }
static int  MS sh_GetStringTypeW(u32 t,const u16*s,int c,u16*out){native_trace("sh_GetStringTypeW"); for(int i=0;i<c;i++) out[i]=0; return 1; }

// misc / version / cpu
static void MS sh_GetSystemInfo(void*p){native_trace("sh_GetSystemInfo"); unsupported("GetSystemInfo"); }
static void MS sh_GetSystemTimeAsFileTime(u64*p){native_trace("sh_GetSystemTimeAsFileTime");struct timespec t;clock_gettime(CLOCK_REALTIME,&t);*p=((u64)t.tv_sec+11644473600ULL)*10000000+t.tv_nsec/100;}
static u32 MS sh_GetTickCount(void){native_trace("sh_GetTickCount");struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (u32)((u64)t.tv_sec*1000+t.tv_nsec/1000000);}
static int MS sh_QueryPerformanceCounter(u64*p){native_trace("sh_QueryPerformanceCounter");struct timespec t;if(!p||clock_gettime(CLOCK_MONOTONIC,&t))return 0;*p=(u64)t.tv_sec*1000000000+t.tv_nsec;return 1;}
static int  MS sh_IsDebuggerPresent(void){native_trace("sh_IsDebuggerPresent"); return 0; }
static int MS sh_IsProcessorFeaturePresent(u32 f){native_trace("sh_IsProcessorFeaturePresent");return f==6||f==8;}
static void* MS sh_EncodePointer(void*p){native_trace("sh_EncodePointer"); return p; }
static void* MS sh_DecodePointer(void*p){native_trace("sh_DecodePointer"); return p; }
static u64  MS sh_VerSetConditionMask(u64 m,u32 t,u8 c){native_trace("sh_VerSetConditionMask"); return m; }
static int  MS sh_VerifyVersionInfoA(void*vi,u32 tm,u64 cm){native_trace("sh_VerifyVersionInfoA"); return 1; }
static char g_cmd[]="loader"; static u16 g_cmdw[]={'l','o','a','d','e','r',0};
static char* MS sh_GetCommandLineA(void){native_trace("sh_GetCommandLineA"); return g_cmd; }
static u16*  MS sh_GetCommandLineW(void){native_trace("sh_GetCommandLineW"); return g_cmdw; }
static void MS sh_GetStartupInfoW(void*si){native_trace("sh_GetStartupInfoW"); memset(si,0,104); *(u32*)si=104; }
static u16 g_env[2]={0,0};
static u16* MS sh_GetEnvironmentStringsW(void){native_trace("sh_GetEnvironmentStringsW"); return g_env; }
static int  MS sh_FreeEnvironmentStringsW(void*p){native_trace("sh_FreeEnvironmentStringsW"); return 1; }

// exception/unwind (only hit if the engine throws — hope not)
static void MS sh_RtlCaptureContext(void*ctx){native_trace("sh_RtlCaptureContext"); unsupported("RtlCaptureContext"); }
static void* MS sh_RtlLookupFunctionEntry(u64 pc,u64*base,void*hist){native_trace("sh_RtlLookupFunctionEntry"); unsupported("RtlLookupFunctionEntry"); }
static void* MS sh_RtlVirtualUnwind(u32 t,u64 b,u64 pc,void*fe,void*ctx,void**hd,u64*est,void*ctxp){native_trace("sh_RtlVirtualUnwind"); unsupported("RtlVirtualUnwind"); }
static void MS sh_RtlUnwindEx(void*a,void*b,void*c,void*d,void*e,void*f){native_trace("sh_RtlUnwindEx"); unsupported("RtlUnwindEx"); }
static void* MS sh_RtlPcToFileHeader(void*pc,void**base){native_trace("sh_RtlPcToFileHeader"); if(base)*base=(void*)g_image; return (void*)g_image; }
static void* MS sh_SetUnhandledExceptionFilter(void*f){native_trace("sh_SetUnhandledExceptionFilter"); return 0; }
static u32  MS sh_UnhandledExceptionFilter(void*p){native_trace("sh_UnhandledExceptionFilter"); return 1; }
static void MS sh_RaiseException(u32 code,u32 fl,u32 n,void*a){native_trace("sh_RaiseException"); unsupported("RaiseException"); }
static void MS sh_TerminateProcess(void*h,u32 c){native_trace("sh_TerminateProcess"); unsupported("TerminateProcess"); }
static void MS sh_ExitProcess(u32 c){native_trace("sh_ExitProcess"); unsupported("ExitProcess"); }

static void MS sh_Sleep(u32 ms){native_trace("sh_Sleep");if(ms>10000)unsupported("Sleep excessive");struct timespec t={ms/1000,(ms%1000)*1000000L};while(nanosleep(&t,&t)&&errno==EINTR); }
static int MS sh_QueryPerformanceFrequency(u64*p){native_trace("sh_QueryPerformanceFrequency");if(!p)return 0;*p=1000000000;return 1;}
static void MS sh_GetLocalTime(u16*p){native_trace("sh_GetLocalTime");struct timespec t;clock_gettime(CLOCK_REALTIME,&t);struct tm b;localtime_r(&t.tv_sec,&b);u16 v[8]={b.tm_year+1900,b.tm_mon+1,b.tm_wday,b.tm_mday,b.tm_hour,b.tm_min,b.tm_sec,t.tv_nsec/1000000};memcpy(p,v,16);}
static u64 MS sh_SetEndOfFile(void){native_trace("sh_SetEndOfFile");unsupported("SetEndOfFile");return 0;}
static void* MS sh_InterlockedPushEntrySList(void*p,void*entry){native_trace("sh_InterlockedPushEntrySList");NativeSList*l=slist_get(p,0);void*old=l->head;*(void**)entry=old;l->head=entry;return old;}
static void* MS sh_GetCurrentThread(void){native_trace("sh_GetCurrentThread");return (void*)(intptr_t)-2;}
static u64 MS sh_ReadFile(void){native_trace("sh_ReadFile");unsupported("ReadFile");return 0;}
static u64 MS sh_ReadConsoleW(void){native_trace("sh_ReadConsoleW");unsupported("ReadConsoleW");return 0;}
static u64 MS sh_GetConsoleOutputCP(void){native_trace("sh_GetConsoleOutputCP");unsupported("GetConsoleOutputCP");return 0;}
static u64 MS sh_GetFileSizeEx(void){native_trace("sh_GetFileSizeEx");unsupported("GetFileSizeEx");return 0;}
static u64 MS sh_GetTempPathW(void){native_trace("sh_GetTempPathW");unsupported("GetTempPathW");return 0;}
static void (MS *fls_callbacks[1088])(void*);
static u32 MS sh_FlsAlloc(void(MS *callback)(void*)){native_trace("sh_FlsAlloc");u32 i=sh_TlsAlloc();fls_callbacks[i]=callback;return i;}
static void* MS sh_FlsGetValue(u32 i){native_trace("sh_FlsGetValue");return sh_TlsGetValue(i);}
static int MS sh_FlsSetValue(u32 i,void*p){native_trace("sh_FlsSetValue");return sh_TlsSetValue(i,p);}
static int MS sh_FlsFree(u32 i){native_trace("sh_FlsFree");if(i>=1088)unsupported("FLS index");if(g_tls_vals[i]&&fls_callbacks[i])fls_callbacks[i](g_tls_vals[i]);g_tls_vals[i]=NULL;fls_callbacks[i]=NULL;return 1;}
static u64 MS sh_GetDateFormatW(void){native_trace("sh_GetDateFormatW");unsupported("GetDateFormatW");return 0;}
static u64 MS sh_GetTimeFormatW(void){native_trace("sh_GetTimeFormatW");unsupported("GetTimeFormatW");return 0;}
static u64 MS sh_CompareStringW(void){native_trace("sh_CompareStringW");unsupported("CompareStringW");return 0;}
static u64 MS sh_GetLocaleInfoW(void){native_trace("sh_GetLocaleInfoW");unsupported("GetLocaleInfoW");return 0;}
static u64 MS sh_IsValidLocale(void){native_trace("sh_IsValidLocale");unsupported("IsValidLocale");return 0;}
static u64 MS sh_GetUserDefaultLCID(void){native_trace("sh_GetUserDefaultLCID");unsupported("GetUserDefaultLCID");return 0;}
static u64 MS sh_EnumSystemLocalesW(void){native_trace("sh_EnumSystemLocalesW");unsupported("EnumSystemLocalesW");return 0;}
static u64 MS sh_GetFileAttributesExW(void){native_trace("sh_GetFileAttributesExW");unsupported("GetFileAttributesExW");return 0;}
static u64 MS sh_CreateDirectoryW(void){native_trace("sh_CreateDirectoryW");unsupported("CreateDirectoryW");return 0;}
static u64 MS sh_FindFirstFileExW(void){native_trace("sh_FindFirstFileExW");unsupported("FindFirstFileExW");return 0;}
static u64 MS sh_FindNextFileW(void){native_trace("sh_FindNextFileW");unsupported("FindNextFileW");return 0;}
static u64 MS sh_SetEnvironmentVariableW(void){native_trace("sh_SetEnvironmentVariableW");unsupported("SetEnvironmentVariableW");return 0;}
static u64 MS sh_SetConsoleCtrlHandler(void){native_trace("sh_SetConsoleCtrlHandler");unsupported("SetConsoleCtrlHandler");return 0;}
static u64 MS sh_RtlUnwind(void){native_trace("sh_RtlUnwind");unsupported("RtlUnwind");return 0;}
static u64 MS sh_RegQueryValueExA(void){native_trace("sh_RegQueryValueExA");unsupported("RegQueryValueExA");return 0;}
static u32 MS sh_RegOpenKeyExA(void*root,const char*key,u32 options,u32 access,void**out){
  native_trace("sh_RegOpenKeyExA");fprintf(stderr,"registry absent: %s\n",key?key:"(null)");
  if(!key||strcmp(key,"SYSTEM\\CurrentControlSet\\Control\\YamilaFP")||options||!out)unsupported("RegOpenKeyExA outside fixed empty config");
  *out=NULL;return 2;
}
static u64 MS sh_RegCloseKey(void){native_trace("sh_RegCloseKey");unsupported("RegCloseKey");return 0;}
static u64 MS sh_RegSetKeyValueA(void){native_trace("sh_RegSetKeyValueA");unsupported("RegSetKeyValueA");return 0;}
static u64 MS sh_SetupDiDestroyDeviceInfoList(void){native_trace("sh_SetupDiDestroyDeviceInfoList");unsupported("SetupDiDestroyDeviceInfoList");return 0;}
static u64 MS sh_SetupDiEnumDeviceInfo(void){native_trace("sh_SetupDiEnumDeviceInfo");unsupported("SetupDiEnumDeviceInfo");return 0;}
static u64 MS sh_SetupDiGetDeviceInstanceIdA(void){native_trace("sh_SetupDiGetDeviceInstanceIdA");unsupported("SetupDiGetDeviceInstanceIdA");return 0;}
static u64 MS sh_SetupDiGetClassDevsA(void){native_trace("sh_SetupDiGetClassDevsA");unsupported("SetupDiGetClassDevsA");return 0;}
static u64 MS sh_SetupDiClassGuidsFromNameExA(void){native_trace("sh_SetupDiClassGuidsFromNameExA");unsupported("SetupDiClassGuidsFromNameExA");return 0;}
static void register_shims(void){
#define R(n) reg(#n, (void*)sh_##n)
  R(SetLastError);R(GetLastError);R(GetProcessHeap);R(HeapAlloc);R(HeapFree);R(HeapReAlloc);
  R(HeapSize);R(HeapValidate);R(HeapQueryInformation);
  reg("InitializeCriticalSection",sh_InitCS);reg("InitializeCriticalSectionAndSpinCount",sh_InitCSSpin);
  reg("EnterCriticalSection",sh_EnterCS);reg("LeaveCriticalSection",sh_LeaveCS);reg("DeleteCriticalSection",sh_DeleteCS);
  reg("InitializeSListHead",sh_InitSList);reg("InterlockedFlushSList",sh_FlushSList);
  R(TlsAlloc);R(TlsFree);R(TlsGetValue);R(TlsSetValue);
  R(GetCurrentProcess);R(GetCurrentProcessId);R(GetCurrentThreadId);
  R(GetModuleHandleW);R(GetModuleHandleA);R(GetModuleHandleExW);R(GetModuleFileNameA);R(GetModuleFileNameW);
  R(LoadLibraryExW);R(FreeLibrary);R(GetProcAddress);
  R(GetStdHandle);R(SetStdHandle);R(GetFileType);R(GetConsoleMode);R(GetConsoleCP);
  R(WriteFile);R(WriteConsoleW);R(OutputDebugStringA);R(OutputDebugStringW);R(FlushFileBuffers);
  R(CreateFileW);R(SetFilePointerEx);R(CloseHandle);R(FindFirstFileExA);R(FindNextFileA);R(FindClose);R(GetSystemDirectoryA);
  R(CreateEventW);R(SetEvent);R(ResetEvent);R(WaitForSingleObject);R(WaitForSingleObjectEx);R(CreateThread);R(DeviceIoControl);
  R(GetACP);R(GetOEMCP);R(GetCPInfo);R(IsValidCodePage);R(MultiByteToWideChar);R(WideCharToMultiByte);R(LCMapStringW);R(GetStringTypeW);
  R(GetSystemInfo);R(GetSystemTimeAsFileTime);R(GetTickCount);R(QueryPerformanceCounter);R(IsDebuggerPresent);R(IsProcessorFeaturePresent);
  R(EncodePointer);R(DecodePointer);R(VerSetConditionMask);R(VerifyVersionInfoA);
  R(GetCommandLineA);R(GetCommandLineW);R(GetStartupInfoW);R(GetEnvironmentStringsW);R(FreeEnvironmentStringsW);
  R(RtlCaptureContext);R(RtlLookupFunctionEntry);R(RtlVirtualUnwind);R(RtlUnwindEx);R(RtlPcToFileHeader);
  R(SetUnhandledExceptionFilter);R(UnhandledExceptionFilter);R(RaiseException);R(TerminateProcess);R(ExitProcess);
  R(Sleep);
  R(QueryPerformanceFrequency);
  R(GetLocalTime);
  R(SetEndOfFile);
  R(InterlockedPushEntrySList);
  R(GetCurrentThread);
  R(ReadFile);
  R(ReadConsoleW);
  R(GetConsoleOutputCP);
  R(GetFileSizeEx);
  R(GetTempPathW);
  R(FlsAlloc);
  R(FlsGetValue);
  R(FlsSetValue);
  R(FlsFree);
  R(GetDateFormatW);
  R(GetTimeFormatW);
  R(CompareStringW);
  R(GetLocaleInfoW);
  R(IsValidLocale);
  R(GetUserDefaultLCID);
  R(EnumSystemLocalesW);
  R(GetFileAttributesExW);
  R(CreateDirectoryW);
  R(FindFirstFileExW);
  R(FindNextFileW);
  R(SetEnvironmentVariableW);
  R(SetConsoleCtrlHandler);
  R(RtlUnwind);
  R(RegQueryValueExA);
  R(RegOpenKeyExA);
  R(RegCloseKey);
  R(RegSetKeyValueA);
  R(SetupDiDestroyDeviceInfoList);
  R(SetupDiEnumDeviceInfo);
  R(SetupDiGetDeviceInstanceIdA);
  R(SetupDiGetClassDevsA);
  R(SetupDiClassGuidsFromNameExA);
#undef R
}

// ================= PE LOADER =================
static int load_pe(void){
  int fd=open(g_dllpath,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0){perror("open DLL");return -1;}
  struct stat st;if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_size!=2867104){close(fd);return -1;}
  g_filelen=st.st_size;g_file=malloc(g_filelen);if(!g_file){close(fd);return -1;}
  size_t offset=0;while(offset<(size_t)g_filelen){ssize_t n=read(fd,g_file+offset,g_filelen-offset);if(n<=0){close(fd);return -1;}offset+=n;}close(fd);
  static const u8 expected[32]={0xf7,0x45,0xba,0xf9,0xc9,0x44,0x88,0x47,0x3e,0x98,0x47,0x2a,0x5e,0x77,0x9c,0x12,0x0a,0xbf,0xa7,0x2a,0x20,0x58,0xaf,0x3b,0x9c,0x61,0xc8,0x0a,0xff,0xc7,0xa9,0xc1};
  u8 digest[32];unsigned size=0;if(!EVP_Digest(g_file,g_filelen,digest,&size,EVP_sha256(),NULL)||size!=32||memcmp(expected,digest,32)){fprintf(stderr,"DLL hash mismatch\n");return -1;}

  u32 e=f32(0x3c);
  g_imagebase=f64(e+24+24);
  u32 sizeofimage=f32(e+24+56);
  u32 entry=f32(e+24+16);
  u16 nsec=f16(e+6);
  u16 optsize=f16(e+20);
  u64 sectbl=e+24+optsize;

  if(g_imagebase!=0x180000000ULL||sizeofimage!=0x41a000||f16(e+4)!=0x8664)return -1;
  u32 hdrsize=f32(e+24+60); // SizeOfHeaders

  /* Prepare the fully-resolved image in a scratch buffer (writable, NOT
   * executable), then map it back from an anonymous FILE (memfd) with per-section
   * protections. This keeps code read+execute and data read+write, so no page is
   * ever writable AND executable at once — which lets the engine run under
   * fprintd's MemoryDenyWriteExecute=yes hardening (no systemd override needed).
   * The DLL loads at its preferred base 0x180000000, so no relocations are
   * required. */
  u8 *img=calloc(1,sizeofimage);
  if(!img){ perror("calloc"); return -1; }
  memcpy(img,g_file,hdrsize);
  for(int i=0;i<nsec;i++){
    u64 s=sectbl+i*40;
    u32 vaddr=f32(s+12), rawsize=f32(s+16), rawptr=f32(s+20);
    memcpy(img+vaddr, g_file+rawptr, rawsize);
  }

  /* resolve kernel32 imports into the IAT within the scratch buffer */
  u32 imprva=f32(e+24+112+8*1);
  for(u64 d=imprva;;d+=20){
    u32 orig=*(u32*)(img+d), namer=*(u32*)(img+d+12), fthunk=*(u32*)(img+d+16);
    if(namer==0) break;
    const char*module=(char*)img+namer;
    if(strcmp(module,"KERNEL32.dll")&&strcmp(module,"ADVAPI32.dll")&&strcmp(module,"SETUPAPI.dll")){free(img);return -1;}
    u64 rt=orig?orig:fthunk;
    for(int j=0;;j++){
      u64 ent=*(u64*)(img+rt+j*8);
      if(!ent) break;
      u64 *slot=(u64*)(img+fthunk+j*8);
      if(ent>>63){free(img);return -1;} // by ordinal: none needed
      const char*fn=(char*)(img+(ent&0x7fffffff)+2);
      void*sh=find_shim(fn);
      if(!sh){fprintf(stderr,"missing shim: %s\n",fn);free(img);return -1;}
      imports_resolved++;
      *slot=(u64)sh;
    }
  }

  /* write the prepared image to an anonymous in-memory file */
  int mfd=memfd_create("ftengine",MFD_CLOEXEC);
  if(mfd<0){ perror("memfd_create"); free(img); return -1; }
  ssize_t wr=write(mfd,img,sizeofimage);
  free(img);
  if(wr!=(ssize_t)sizeofimage){ perror("write memfd"); close(mfd); return -1; }

  /* reserve the preferred base, then map each section from the file (W^X-safe) */
  void *m=mmap((void*)g_imagebase,sizeofimage,PROT_NONE,
               MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
  if(m==MAP_FAILED || m!=(void*)g_imagebase){
    fprintf(stderr,"[loader] reserve @%#lx failed (%p)\n",g_imagebase,m); close(mfd); return -1;
  }
  g_image=m;
  u32 hdrmap=(hdrsize+0xfff)&~0xfffu;
  if(mmap(g_image,hdrmap,PROT_READ,MAP_PRIVATE|MAP_FIXED,mfd,0)==MAP_FAILED){
    perror("[loader] map headers"); close(mfd); return -1;
  }
  for(int i=0;i<nsec;i++){
    u64 s=sectbl+i*40;
    u32 vaddr=f32(s+12), vsize=f32(s+8), rawsize=f32(s+16), chars=f32(s+36);
    u32 seglen=(vsize>rawsize?vsize:rawsize); seglen=(seglen+0xfff)&~0xfffu;
    if(vaddr+seglen>sizeofimage) seglen=sizeofimage-vaddr;
    if(!seglen) continue;
    int prot=PROT_READ;
    if(chars&0x20000000) prot|=PROT_EXEC;   // IMAGE_SCN_MEM_EXECUTE
    if(chars&0x80000000) prot|=PROT_WRITE;  // IMAGE_SCN_MEM_WRITE
    if((prot&(PROT_WRITE|PROT_EXEC))==(PROT_WRITE|PROT_EXEC))return -1;
    if(mmap(g_image+vaddr,seglen,prot,MAP_PRIVATE|MAP_FIXED,mfd,vaddr)==MAP_FAILED){
      perror("[loader] map section"); close(mfd); return -1;
    }
  }
  close(mfd);
  fprintf(stderr,"[loader] file-backed image at %#lx (no W+X), entry RVA %#x\n",g_imagebase,entry);

  if(f32(e+24+112+8*9)){fprintf(stderr,"static TLS unsupported for this fixed target\n");return -1;}
  if(syscall(SYS_arch_prctl,ARCH_GET_GS,&old_gs))return -1;
  // fake TEB in %gs
  memset(g_teb,0,sizeof g_teb); memset(g_peb,0,sizeof g_peb);
  *(u64*)(g_teb+0x30)=(u64)g_teb;            // NtTib.Self
  *(u64*)(g_teb+0x08)=(u64)(g_teb+0x2000);   // StackBase (dummy)
  *(u64*)(g_teb+0x10)=(u64)g_teb;            // StackLimit
  *(u64*)(g_teb+0x58)=(u64)g_tls_array;      // ThreadLocalStoragePointer
  *(u64*)(g_teb+0x60)=(u64)g_peb;            // PEB
  if(set_gs(g_teb)!=0){ perror("arch_prctl SET_GS"); return -1; }
  fprintf(stderr,"[loader] TEB installed in %%gs\n");

  // run entry point (DllMain via CRT startup)
  int(MS *DllMain)(void*,u32,void*)=(void*)(g_image+entry);
  fprintf(stderr,"[loader] calling entry (DllMain) ...\n");
  int r=DllMain((void*)g_imagebase,DLL_PROCESS_ATTACH,0);
  fprintf(stderr,"[loader] DllMain returned %d\n",r);
  return r?0:-2;
}

// find an export by name
static void* get_export(const char*want){
  u32 e=f32(0x3c);
  u32 exprva=f32(e+24+112+8*0);
  u32 nnames=*(u32*)(g_image+exprva+24);
  u32 fns=*(u32*)(g_image+exprva+28);
  u32 names=*(u32*)(g_image+exprva+32);
  u32 ords=*(u32*)(g_image+exprva+36);
  for(u32 i=0;i<nnames;i++){
    u32 nrva=*(u32*)(g_image+names+i*4);
    if(!strcmp((char*)(g_image+nrva),want)){
      u16 ord=*(u16*)(g_image+ords+i*2);
      u32 frva=*(u32*)(g_image+fns+ord*4);
      return g_image+frva;
    }
  }
  return 0;
}


static int native_open(const char *path){g_dllpath=path;register_shims();return load_pe();}
static void native_close(void){
  if(g_image){int(MS *entry)(void*,u32,void*)=(void*)(g_image+f32(f32(0x3c)+24+16));entry(g_image,0,NULL);}
  set_gs((void*)old_gs);
}
static void native_audit(void){
  printf("{\"event\":\"native_audit\",\"imports_resolved\":%u,\"unsupported_calls\":%u,\"api_calls\":{",imports_resolved,unsupported_calls);
  for(unsigned i=0;i<traces;i++)printf("%s\"%s\":%u",i?",":"",trace_name[i],trace_count[i]);
  puts("}}");fflush(stdout);
}
