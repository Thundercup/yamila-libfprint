/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Minimal layout declarations for the already verified x64 WinBio interface. */
#ifndef YAMILA_NATIVE_ABI_H
#define YAMILA_NATIVE_ABI_H
#define WINAPI __attribute__((ms_abi))
#define ENGINE_PROBE_PORTABLE_ABI_CHECK
#include "winbio_compat.h"
typedef uint8_t BYTE,UCHAR,BOOLEAN;
typedef uint16_t WORD;
typedef uint32_t DWORD,ULONG;
typedef int32_t HRESULT;
#define FALSE 0
#define TRUE 1
#define S_OK ((HRESULT)0)
#define E_INVALIDARG ((HRESULT)0x80070057u)
#define E_POINTER ((HRESULT)0x80004003u)
#define E_OUTOFMEMORY ((HRESULT)0x8007000eu)
#define E_NOTIMPL ((HRESULT)0x80004001u)
#define E_UNEXPECTED ((HRESULT)0x8000ffffu)
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define SecureZeroMemory(p,n) explicit_bzero((p),(n))
#endif
