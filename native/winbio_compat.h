/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef ENGINE_PROBE_WINBIO_COMPAT_H
#define ENGINE_PROBE_WINBIO_COMPAT_H

/*
 * Layout-only fallback for current public WINBIO_ENGINE_INTERFACE and
 * WINBIO_PIPELINE shapes.
 * Prefer the Windows SDK's <winbio_adapter.h>. Callback prototypes are
 * intentionally opaque here because this probe never invokes callbacks.
 */
#include <stddef.h>
#include <stdint.h>
#include "engine_callback_fields.def.h"

#if defined(ENGINE_PROBE_PORTABLE_ABI_CHECK)
typedef uint16_t USHORT;
typedef size_t SIZE_T;
typedef int32_t WINBIO_ADAPTER_TYPE;
typedef void *HANDLE;
typedef void *PVOID;
typedef struct _GUID {
    uint32_t Data1;
    uint16_t Data2;
    uint16_t Data3;
    uint8_t Data4[8];
} GUID;
#ifndef WINAPI
#define WINAPI
#endif
#else
#include <windows.h>
typedef int32_t WINBIO_ADAPTER_TYPE;
#endif

typedef struct _WINBIO_ADAPTER_INTERFACE_VERSION {
    USHORT MajorVersion;
    USHORT MinorVersion;
} WINBIO_ADAPTER_INTERFACE_VERSION;

typedef void (WINAPI *WINBIO_ENGINE_CALLBACK)(void);

#pragma pack(push, 8)
typedef struct _WINBIO_ENGINE_INTERFACE {
    WINBIO_ADAPTER_INTERFACE_VERSION Version;
    WINBIO_ADAPTER_TYPE Type;
    SIZE_T Size;
    GUID AdapterId;
#define ENGINE_PROBE_DECLARE_CALLBACK(name) WINBIO_ENGINE_CALLBACK name;
    ENGINE_PROBE_ENGINE_CALLBACK_FIELDS(ENGINE_PROBE_DECLARE_CALLBACK)
#undef ENGINE_PROBE_DECLARE_CALLBACK
} WINBIO_ENGINE_INTERFACE, *PWINBIO_ENGINE_INTERFACE;
#pragma pack(pop)

typedef struct _WINBIO_SENSOR_INTERFACE WINBIO_SENSOR_INTERFACE,
    *PWINBIO_SENSOR_INTERFACE;
typedef struct _WINBIO_STORAGE_INTERFACE WINBIO_STORAGE_INTERFACE,
    *PWINBIO_STORAGE_INTERFACE;
typedef struct _WINBIO_FRAMEWORK_INTERFACE WINBIO_FRAMEWORK_INTERFACE,
    *PWINBIO_FRAMEWORK_INTERFACE;

typedef struct _WINBIO_PIPELINE {
    HANDLE SensorHandle;
    HANDLE EngineHandle;
    HANDLE StorageHandle;
    PWINBIO_SENSOR_INTERFACE SensorInterface;
    PWINBIO_ENGINE_INTERFACE EngineInterface;
    PWINBIO_STORAGE_INTERFACE StorageInterface;
    PVOID SensorContext;
    PVOID EngineContext;
    PVOID StorageContext;
    PWINBIO_FRAMEWORK_INTERFACE FrameworkInterface;
} WINBIO_PIPELINE, *PWINBIO_PIPELINE;

#endif
