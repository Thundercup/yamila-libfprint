/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Test-only storage adapter: one record, owned in process memory. */
typedef struct { DWORD Type; DWORD SidSize; BYTE Sid[68]; } TEST_IDENTITY;
typedef struct {
    TEST_IDENTITY *Identity; UCHAR SubFactor;
    ULONG *IndexVector; SIZE_T IndexElementCount;
    BYTE *TemplateBlob; SIZE_T TemplateBlobSize;
    BYTE *PayloadBlob; SIZE_T PayloadBlobSize;
} TEST_RECORD;
struct _WINBIO_STORAGE_INTERFACE {
    WINBIO_ADAPTER_INTERFACE_VERSION Version;
    WINBIO_ADAPTER_TYPE Type; SIZE_T Size; GUID AdapterId;
    WINBIO_ENGINE_CALLBACK Slots[30];
};
_Static_assert(sizeof(TEST_IDENTITY)==76,"identity ABI");
_Static_assert(sizeof(TEST_RECORD)==64,"record ABI");
_Static_assert(offsetof(TEST_RECORD,TemplateBlob)==32,"template ABI");
_Static_assert(offsetof(WINBIO_STORAGE_INTERFACE,Slots)==32,"storage ABI");
static TEST_IDENTITY test_id={3,12,{1,1,0,0,0,0,0,5,21,0,0,0}};
static TEST_IDENTITY stored_id;
static TEST_RECORD stored;
static int record_present, selected;
static unsigned storage_queries, storage_adds, storage_reads, storage_nexts;
#define NO_RESULTS ((HRESULT)0x8009801fu)
#define NO_MORE ((HRESULT)0x80098020u)
static void release_record(void) {
    if(stored.TemplateBlob) { SecureZeroMemory(stored.TemplateBlob,stored.TemplateBlobSize); free(stored.TemplateBlob); }
    if(stored.PayloadBlob) { SecureZeroMemory(stored.PayloadBlob,stored.PayloadBlobSize); free(stored.PayloadBlob); }
    free(stored.IndexVector); memset(&stored,0,sizeof(stored)); record_present=selected=0;
}
static HRESULT WINAPI mem_query(PWINBIO_PIPELINE p,TEST_IDENTITY *id,UCHAR sub) {
    (void)p; ++storage_queries;
    selected=record_present && id && memcmp(id,&stored_id,sizeof(stored_id))==0 && sub==stored.SubFactor;
    printf("{\"event\":\"storage_query\",\"found\":%s}\n",selected?"true":"false");
    return selected?S_OK:NO_RESULTS;
}
static HRESULT WINAPI mem_content(PWINBIO_PIPELINE p,UCHAR sub,ULONG *index,SIZE_T count) {
    (void)p; (void)sub; (void)index; (void)count; ++storage_queries;
    selected=record_present;
    printf("{\"event\":\"storage_content_query\",\"found\":%s}\n",selected?"true":"false");
    return selected?S_OK:NO_RESULTS;
}
static HRESULT WINAPI mem_add(PWINBIO_PIPELINE p,TEST_RECORD *r) {
    (void)p; ++storage_adds;
    if(r) printf("{\"event\":\"storage_add_received\",\"identity_present\":%s,\"template_present\":%s,\"template_bytes\":%llu,\"index_elements\":%llu,\"payload_bytes\":%llu}\n",
                 r->Identity?"true":"false",r->TemplateBlob?"true":"false",
                 (unsigned long long)r->TemplateBlobSize,(unsigned long long)r->IndexElementCount,
                 (unsigned long long)r->PayloadBlobSize);
    if(record_present || !r || !r->Identity || !r->TemplateBlob || !r->TemplateBlobSize ||
       r->TemplateBlobSize>16*1024*1024 || r->IndexElementCount>4096 || r->PayloadBlobSize>1024*1024 ||
       (r->IndexElementCount && !r->IndexVector) || (r->PayloadBlobSize && !r->PayloadBlob)) return E_INVALIDARG;
    stored=*r; stored_id=*r->Identity; stored.Identity=&stored_id;
    stored.TemplateBlob=malloc(r->TemplateBlobSize);
    stored.IndexVector=r->IndexElementCount?malloc(r->IndexElementCount*sizeof(ULONG)):NULL;
    stored.PayloadBlob=r->PayloadBlobSize?malloc(r->PayloadBlobSize):NULL;
    if(!stored.TemplateBlob || (r->IndexElementCount && !stored.IndexVector) ||
       (r->PayloadBlobSize && !stored.PayloadBlob)) {release_record();return E_OUTOFMEMORY;}
    memcpy(stored.TemplateBlob,r->TemplateBlob,r->TemplateBlobSize);
    if(r->IndexElementCount) memcpy(stored.IndexVector,r->IndexVector,r->IndexElementCount*sizeof(ULONG));
    if(r->PayloadBlobSize) memcpy(stored.PayloadBlob,r->PayloadBlob,r->PayloadBlobSize);
    record_present=1;
    printf("{\"event\":\"storage_add\",\"template_bytes\":%llu,\"index_elements\":%llu,\"payload_bytes\":%llu}\n",
           (unsigned long long)stored.TemplateBlobSize,(unsigned long long)stored.IndexElementCount,
           (unsigned long long)stored.PayloadBlobSize);
    return S_OK;
}
static HRESULT WINAPI mem_get(PWINBIO_PIPELINE p,TEST_RECORD *r) {
    (void)p; ++storage_reads; if(!selected || !r)return NO_RESULTS; *r=stored; return S_OK;
}
static HRESULT WINAPI mem_next(PWINBIO_PIPELINE p) {
    (void)p; ++storage_nexts; selected=0; return NO_MORE;
}
static HRESULT WINAPI mem_first(PWINBIO_PIPELINE p) {(void)p;selected=record_present;return selected?S_OK:NO_RESULTS;}
static HRESULT WINAPI mem_count(PWINBIO_PIPELINE p,SIZE_T *count) {(void)p;if(!count)return E_POINTER;*count=selected?1:0;return S_OK;}
static WINBIO_STORAGE_INTERFACE memory_storage;
static void init_storage(void) {
    memset(&memory_storage,0,sizeof(memory_storage));
    memory_storage.Version.MajorVersion=1; memory_storage.Type=3; memory_storage.Size=sizeof(memory_storage);
#define SET_SLOT(n,f) do { __typeof__(&f) cb=&f; memcpy(&memory_storage.Slots[n],&cb,sizeof(cb)); } while(0)
    SET_SLOT(12,mem_content); SET_SLOT(9,mem_add); SET_SLOT(11,mem_query); SET_SLOT(13,mem_count);
    SET_SLOT(14,mem_first); SET_SLOT(15,mem_next); SET_SLOT(16,mem_get);
#undef SET_SLOT
}
typedef HRESULT (WINAPI *COMMIT_FN)(PWINBIO_PIPELINE,TEST_IDENTITY*,UCHAR,BYTE*,SIZE_T);
typedef HRESULT (WINAPI *VERIFY_FN)(PWINBIO_PIPELINE,TEST_IDENTITY*,UCHAR,BOOLEAN*,BYTE**,SIZE_T*,BYTE**,SIZE_T*,DWORD*);

typedef HRESULT (WINAPI *DUPLICATE_FN)(PWINBIO_PIPELINE,TEST_IDENTITY*,UCHAR*,BOOLEAN*);
