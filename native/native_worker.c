/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Native Linux ELF worker; IPC and storage adapted from the verified Wine probe. */
#include "native_loader.c"
#include "native_abi.h"
#include <sys/resource.h>
typedef void *PWINBIO_BIR;
typedef HRESULT (WINAPI *PIPELINE_FN)(PWINBIO_PIPELINE);
typedef HRESULT (WINAPI *UPDATE_FN)(PWINBIO_PIPELINE,DWORD*);
typedef HRESULT (WINAPI *ACCEPT_FN)(PWINBIO_PIPELINE,void*,SIZE_T,UCHAR,DWORD*);
static void event(const char *stage, HRESULT hr, DWORD detail, int index)
{
    printf("{\"event\":\"callback\",\"stage\":\"%s\",\"index\":%d,"
           "\"hresult\":\"0x%08lX\",\"reject_detail\":%lu}\n",
           stage, index, (unsigned long)(DWORD)hr, (unsigned long)detail);
    fflush(stdout);
}

#include "memory_storage.h"

#include <fcntl.h>

#define MAX_TEMPLATE (2u*1024u*1024u)
#define MAX_PAYLOAD (1024u*1024u)
#define MAX_PACKET (12u+MAX_TEMPLATE+4096u*4u+MAX_PAYLOAD)
static int read_exact(void *out, size_t count) {
    BYTE *p=out;
    while(count) { size_t got=fread(p,1,count,stdin); if(!got)return 0; p+=got;count-=got; }
    return 1;
}
static void hex(const BYTE *data,SIZE_T size) {
    static const char digits[]="0123456789abcdef";
    for(SIZE_T i=0;i<size;++i) { putchar(digits[data[i]>>4]);putchar(digits[data[i]&15]); }
}
static int valid_bir(BYTE *data,DWORD count,UCHAR purpose) {
    return count==5256 && *(DWORD*)(data)==48 && *(DWORD*)(data+4)==32 &&
           *(DWORD*)(data+8)==5176 && *(DWORD*)(data+12)==80 &&
           !*(DWORD*)(data+16) && !*(DWORD*)(data+20) &&
           !*(DWORD*)(data+24) && !*(DWORD*)(data+28) &&
           *(DWORD*)(data+40)==8 && data[45]==purpose &&
           *(WORD*)(data+72)==0x1b && *(WORD*)(data+74)==0x401 &&
           data[114]==8 && !data[115] &&
           *(WORD*)(data+124)==64 && *(WORD*)(data+126)==80;
}
static HRESULT import_record(BYTE *data,DWORD count) {
    if(count<12 || record_present)return E_INVALIDARG;
    DWORD size=*(DWORD*)data,index=*(DWORD*)(data+4),payload=*(DWORD*)(data+8);
    if(!size || size>MAX_TEMPLATE || index>4096 || payload>MAX_PAYLOAD ||
       (SIZE_T)count!=12+(SIZE_T)size+(SIZE_T)index*4+payload)return E_INVALIDARG;
    TEST_RECORD record={0}; record.Identity=&test_id;record.SubFactor=1;
    record.TemplateBlob=data+12;record.TemplateBlobSize=size;
    record.IndexVector=(ULONG*)(data+12+size);record.IndexElementCount=index;
    record.PayloadBlob=data+12+size+index*4;record.PayloadBlobSize=payload;
    return mem_add(NULL,&record);
}

static const char *current_stage="load";
static unsigned call_count(const char*name){for(unsigned i=0;i<traces;i++)if(!strcmp(name,trace_name[i]))return trace_count[i];return 0;}
int main(int argc,char **argv) {
    struct rlimit core={0,0}, inherited_core;
    if(geteuid()==0)return 77;
    if(getrlimit(RLIMIT_CORE,&inherited_core) ||
       ((inherited_core.rlim_cur || inherited_core.rlim_max) && setrlimit(RLIMIT_CORE,&core)))return 3;
    PWINBIO_ENGINE_INTERFACE table=NULL;
    PIPELINE_FN attach,init,create,discard,detach;
    UPDATE_FN update;ACCEPT_FN accept;COMMIT_FN commit;VERIFY_FN verify;DUPLICATE_FN duplicate;
    WINBIO_PIPELINE pipeline={0};HRESULT hr;
    int enrolling=0,complete=0,exit_status=0;
    if(argc!=2)return 2;
    if(native_open(argv[1]))return 4;
    HRESULT(WINAPI *query)(PWINBIO_ENGINE_INTERFACE*)=get_export("WbioQueryEngineInterface");
    if(!query)return 5;hr=query(&table);
    if(hr || !table || (u8*)table<g_image || (u8*)table+360>g_image+0x41a000 || table->Size!=360 || table->Version.MajorVersion!=6)return 6;
#define GET(name,dst) memcpy(&(dst),&table->name,sizeof(dst))
    GET(Attach,attach);GET(PipelineInit,init);GET(CreateEnrollment,create);
    GET(DiscardEnrollment,discard);GET(Detach,detach);GET(UpdateEnrollment,update);
    GET(AcceptSampleData,accept);GET(CheckForDuplicate,duplicate);
    GET(CommitEnrollment,commit);GET(VerifyFeatureSet,verify);
#undef GET
    if(!attach||!init||!create||!discard||!detach||!update||!accept||!duplicate||!commit||!verify)return 8;
    pipeline.SensorHandle=pipeline.EngineHandle=pipeline.StorageHandle=INVALID_HANDLE_VALUE;
    pipeline.EngineInterface=table;init_storage();pipeline.StorageInterface=&memory_storage;
    current_stage="Attach";hr=attach(&pipeline);event(current_stage,hr,0,-1);if(hr!=S_OK)return 10;
    current_stage="PipelineInit";hr=init(&pipeline);event(current_stage,hr,0,-1);if(hr!=S_OK)return 22;
    puts("{\"event\":\"ready\",\"ipc_version\":1,\"runtime\":\"linux-pe\"}");fflush(stdout);
    for(;;) {
        BYTE header[5];BYTE *data=NULL;DWORD count;UCHAR op;
        DWORD detail=0xffffffffu;BOOLEAN matched=FALSE;
        int first=fgetc(stdin);
        if(first==EOF)break;
        header[0]=(BYTE)first;
        if(!read_exact(header+1,4)){exit_status=42;break;}
        op=header[0];memcpy(&count,header+1,4);
        if(count>MAX_PACKET) {exit_status=40;break;}
        if(count) {
            data=malloc(count);if(!data){exit_status=41;break;}
            if(!read_exact(data,count)){free(data);exit_status=42;break;}
        }
        hr=E_INVALIDARG;
        if(op==1 && !count && !enrolling && !record_present) {
            current_stage="CreateEnrollment";hr=create(&pipeline);
            if(hr==S_OK){enrolling=1;complete=0;}
        } else if(op==2 && enrolling && !complete && valid_bir(data,count,4)) {
            current_stage="AcceptSampleData.ENROLL";hr=accept(&pipeline,(PWINBIO_BIR)data,count,4,&detail);
            event(current_stage,hr,detail,-1);
            if(hr==S_OK) {
                detail=0xffffffffu;current_stage="UpdateEnrollment";hr=update(&pipeline,&detail);
                if(hr==S_OK)complete=1;
            }
        } else if(op==3 && record_present && valid_bir(data,count,1)) {
            BYTE *payload=NULL,*hash=NULL;SIZE_T payload_size=0,hash_size=0;
            current_stage="AcceptSampleData.VERIFY";hr=accept(&pipeline,(PWINBIO_BIR)data,count,1,&detail);
            event(current_stage,hr,detail,-1);
            if(hr==S_OK) {
                detail=0xffffffffu;current_stage="VerifyFeatureSet";
                hr=verify(&pipeline,&test_id,1,&matched,&payload,&payload_size,&hash,&hash_size,&detail);
                if(payload||hash){hr=E_NOTIMPL;matched=FALSE;}
            }
        } else if(op==4 && !enrolling) {
            current_stage="ImportRecord";hr=import_record(data,count);
        } else if(op==6 && !count && enrolling && complete) {
            TEST_IDENTITY found={0};UCHAR sub=0;BOOLEAN dup=FALSE;
            current_stage="CheckForDuplicate";hr=duplicate(&pipeline,&found,&sub,&dup);
            event(current_stage,hr,dup,-1);
            if(hr==S_OK && !dup) {
                current_stage="CommitEnrollment";hr=commit(&pipeline,&test_id,1,NULL,0);
                if(hr==S_OK && record_present)enrolling=0;
                else if(hr==S_OK)hr=E_UNEXPECTED;
            } else if(hr==S_OK)hr=(HRESULT)0x8009801cu;
        } else if(op==5 && !count)hr=S_OK;
        if(data){SecureZeroMemory(data,count);free(data);}
        printf("{\"event\":\"result\",\"op\":%u,\"hresult\":\"0x%08lX\",\"reject_detail\":%lu,\"complete\":%s,\"match\":%s",
               op,(unsigned long)(DWORD)hr,(unsigned long)detail,complete?"true":"false",matched?"true":"false");
        if(op==6 && hr==S_OK) {
            fputs(",\"record\":{\"template_hex\":\"",stdout);hex(stored.TemplateBlob,stored.TemplateBlobSize);
            fputs("\",\"index_hex\":\"",stdout);hex((BYTE*)stored.IndexVector,stored.IndexElementCount*4);
            fputs("\",\"payload_hex\":\"",stdout);hex(stored.PayloadBlob,stored.PayloadBlobSize);fputs("\"}",stdout);
        }
        puts("}");fflush(stdout);
        if(op==5)break;
    }
    if(enrolling){current_stage="DiscardEnrollment";hr=discard(&pipeline);event(current_stage,hr,0,-1);if(hr!=S_OK)exit_status=43;}
    current_stage="Detach";hr=detach(&pipeline);event(current_stage,hr,0,-1);if(hr!=S_OK)exit_status=44;
    release_record();native_close();native_audit();
    unsigned io=call_count("sh_DeviceIoControl");
    printf("{\"event\":\"closed\",\"runtime\":\"linux-pe\",\"shim\":{\"device_io_control\":{\"calls\":%u,\"allowed\":%u,\"denied\":0},\"create_file_w_calls\":0,\"create_directory_w_calls\":0,\"unsupported_calls\":%u}}\n",io,io,unsupported_calls);fflush(stdout);
    if(io!=1||unsupported_calls)return 11;
    return exit_status;
}
