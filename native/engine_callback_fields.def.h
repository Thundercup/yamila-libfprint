/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef ENGINE_PROBE_CALLBACK_FIELDS_DEF_H
#define ENGINE_PROBE_CALLBACK_FIELDS_DEF_H

/* Order and spelling follow Microsoft's WINBIO_ENGINE_INTERFACE reference. */
#define ENGINE_PROBE_ENGINE_CALLBACK_FIELDS(X) \
    X(Attach) \
    X(Detach) \
    X(ClearContext) \
    X(QueryPreferredFormat) \
    X(QueryIndexVectorSize) \
    X(QueryHashAlgorithms) \
    X(SetHashAlgorithm) \
    X(QuerySampleHint) \
    X(AcceptSampleData) \
    X(ExportEngineData) \
    X(VerifyFeatureSet) \
    X(IdentifyFeatureSet) \
    X(CreateEnrollment) \
    X(UpdateEnrollment) \
    X(GetEnrollmentStatus) \
    X(GetEnrollmentHash) \
    X(CheckForDuplicate) \
    X(CommitEnrollment) \
    X(DiscardEnrollment) \
    X(ControlUnit) \
    X(ControlUnitPrivileged) \
    X(NotifyPowerChange) \
    X(Reserved_1) \
    X(PipelineInit) \
    X(PipelineCleanup) \
    X(Activate) \
    X(Deactivate) \
    X(QueryExtendedInfo) \
    X(IdentifyAll) \
    X(SetEnrollmentSelector) \
    X(SetEnrollmentParameters) \
    X(QueryExtendedEnrollmentStatus) \
    X(RefreshCache) \
    X(SelectCalibrationFormat) \
    X(QueryCalibrationData) \
    X(SetAccountPolicy) \
    X(CreateKey) \
    X(IdentifyFeatureSetSecure) \
    X(AcceptPrivateSensorTypeInfo) \
    X(CreateEnrollmentAuthenticated) \
    X(IdentifyFeatureSetAuthenticated)

#endif
