/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Yamila 2808:06fc prototype. Vendor code is executed only by a separate,
 * unprivileged broker/ELF worker; the libfprint process never maps the DLL.
 */
#define FP_COMPONENT "yamila"
#include "drivers_api.h"
#include "yamila-paths.h"
#include <pwd.h>
#include <grp.h>
#include <signal.h>
#include <sys/prctl.h>
#include <unistd.h>
#include <string.h>

#define YML_MAX (12u + 2u*1024u*1024u + 4096u*4u + 1024u*1024u)
#define YML_SHA "f745baf9c94488473e98472a5e779c120abfa72a2058af3b9c61c80affc7a9c1"
#define YML_FORMAT "gray8-shift2-64x80-v1"

typedef struct _FpiDeviceYamila {
  FpDevice parent;
  GSubprocess *process;
  GSource *timeout;
  guint generation;
  gboolean timed_out;
  guint pending_mode;
  GBytes *pending_input;
} FpiDeviceYamila;
typedef FpDeviceClass FpiDeviceYamilaClass;
GType fpi_device_yamila_get_type (void);
G_DEFINE_TYPE (FpiDeviceYamila, fpi_device_yamila, FP_TYPE_DEVICE)

typedef struct {
  GSubprocess *process;
  GBytes *input;
  GBytes *output;
  guint mode, generation;
  gboolean match, retry;
} Job;
typedef struct { FpDevice *device; guint generation, stage; gboolean retry; } Progress;
typedef struct { uid_t uid; gid_t gid; pid_t parent; } ChildIdentity;

static void start_io (FpDevice *dev, guint mode, GBytes *input);
static void dev_open (FpDevice *dev);

static gboolean is_virtual (FpDevice *dev) {
  return FP_DEVICE_GET_CLASS (dev)->type == FP_DEVICE_TYPE_VIRTUAL;
}
static void kill_broker (GSubprocess *process) {
  const gchar *id = g_subprocess_get_identifier (process);
  if (id) {
    pid_t pid = (pid_t) g_ascii_strtoll (id, NULL, 10);
    if (pid > 1) kill (-pid, SIGKILL); /* includes algorithm worker */
    g_subprocess_force_exit (process);
  }
}
static void child_setup (gpointer data) {
  ChildIdentity *identity = data;
  if (setsid () < 0) _exit (79);
  if (geteuid () == 0 &&
      (identity->uid == 0 || identity->gid == 0 ||
       setgroups (0, NULL) || setgid (identity->gid) || setuid (identity->uid))) _exit (77);
  if (getuid () != identity->uid || geteuid () != identity->uid ||
      getgid () != identity->gid || getegid () != identity->gid || geteuid () == 0 ||
      prctl (PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) ||
      prctl (PR_SET_PDEATHSIG, SIGTERM) || getppid () != identity->parent) _exit (78);
}
static void job_free (Job *job) {
  g_clear_object (&job->process);
  g_clear_pointer (&job->input, g_bytes_unref);
  g_clear_pointer (&job->output, g_bytes_unref);
  g_free (job);
}
static gboolean progress_main (gpointer data) {
  Progress *p = data;
  FpiDeviceYamila *self = (FpiDeviceYamila *) p->device;
  if (self->generation == p->generation &&
      fpi_device_get_current_action (p->device) == FPI_DEVICE_ACTION_ENROLL &&
      !fpi_device_action_is_cancelled (p->device) && !self->timed_out) {
    fpi_device_enroll_progress (p->device, p->stage, NULL,
       p->retry ? fpi_device_retry_new (FP_DEVICE_RETRY_GENERAL) : NULL);
  }
  g_object_unref (p->device);
  g_free (p);
  return G_SOURCE_REMOVE;
}
static gboolean exact (GInputStream *stream, void *buf, gsize size, GError **error) {
  gsize got = 0;
  if (!g_input_stream_read_all (stream, buf, size, &got, NULL, error)) return FALSE;
  if (got != size) {
    g_set_error_literal (error, G_IO_ERROR, G_IO_ERROR_BROKEN_PIPE, "Yamila broker closed its pipe");
    return FALSE;
  }
  return TRUE;
}
static guint32 u32 (const guint8 *buf) {
  guint32 value;
  memcpy (&value, buf, 4);
  return GUINT32_FROM_LE (value);
}
static gboolean valid_record (const guint8 *buf, gsize size) {
  if (size < 12 || size > YML_MAX) return FALSE;
  guint32 t = u32 (buf), i = u32 (buf + 4), p = u32 (buf + 8);
  return t > 0 && t <= 2u*1024u*1024u && i <= 4096 && p <= 1024u*1024u &&
         size == 12u + (gsize)t + (gsize)i*4u + p;
}
static void io_thread (GTask *task, gpointer source, gpointer data, GCancellable *unused) {
  Job *job = data;
  GInputStream *in = g_subprocess_get_stdout_pipe (job->process);
  GOutputStream *out = g_subprocess_get_stdin_pipe (job->process);
  g_autoptr(GError) error = NULL;
  guint last_stage = 0;
  if (job->mode == 4) {
    g_subprocess_wait (job->process, NULL, NULL);
    g_task_return_new_error (task, G_IO_ERROR, G_IO_ERROR_CANCELLED, "Broker reaped");
    return;
  }
  if (job->mode) {
    guint8 header[5] = {job->mode, 0, 0, 0, 0};
    gsize size = 0, sent;
    gconstpointer body = job->input ? g_bytes_get_data (job->input, &size) : NULL;
    guint32 le = GUINT32_TO_LE ((guint32)size);
    memcpy (header + 1, &le, 4);
    if (!g_output_stream_write_all (out, header, 5, &sent, NULL, &error) ||
        (size && !g_output_stream_write_all (out, body, size, &sent, NULL, &error))) goto fail;
  }
  for (;;) {
    guint8 header[5];
    g_autofree guint8 *body = NULL;
    if (!exact (in, header, 5, &error)) goto fail;
    guint32 size = u32 (header + 1);
    if (size > YML_MAX) goto protocol_error;
    body = g_malloc (MAX (size, 1));
    if (!exact (in, body, size, &error)) goto fail;
    if (header[0] == 'E') {
      g_set_error_literal (&error, G_IO_ERROR, G_IO_ERROR_FAILED,
                           job->mode == 0 ? "Yamila device or algorithm initialization failed" : "Yamila operation failed");
      goto fail;
    }
    if (job->mode == 0 && header[0] == 'R' && size == 4 && !memcmp (body, "YML1", 4)) break;
    if (job->mode == 3 && header[0] == 'C' && size == 0) {
      if (!g_subprocess_wait_check (job->process, NULL, &error)) goto fail;
      break;
    }
    if (job->mode == 1 && ((header[0] == 'P' && size == 4) || (header[0] == 'N' && size == 0))) {
      guint stage = header[0] == 'P' ? u32 (body) : last_stage;
      if (stage < last_stage || stage >= 12) goto protocol_error;
      last_stage = stage;
      Progress *p = g_new0 (Progress, 1);
      p->device = g_object_ref (source); p->generation = job->generation;
      p->stage = stage; p->retry = header[0] == 'N';
      GSource *source_event = g_idle_source_new ();
      g_source_set_priority (source_event, G_PRIORITY_DEFAULT);
      g_source_set_callback (source_event, progress_main, p, NULL);
      g_source_attach (source_event, g_task_get_context (task));
      g_source_unref (source_event);
      continue;
    }
    if (job->mode == 1 && header[0] == 'T' && valid_record (body, size)) {
      job->output = g_bytes_new (body, size);
      break;
    }
    if (job->mode == 2 && header[0] == 'N' && size == 0) {
      job->retry = TRUE; break;
    }
    if (job->mode == 2 && header[0] == 'M' && size == 1 && body[0] <= 1) {
      job->match = body[0]; break;
    }
protocol_error:
    g_set_error_literal (&error, G_IO_ERROR, G_IO_ERROR_INVALID_DATA, "Invalid Yamila broker response");
    goto fail;
  }
  g_task_return_boolean (task, TRUE);
  return;
fail:
  kill_broker (job->process);
  g_subprocess_wait (job->process, NULL, NULL);
  g_task_return_error (task, g_steal_pointer (&error));
}
static void io_complete (GObject *object, GAsyncResult *result, gpointer unused) {
  FpDevice *dev = FP_DEVICE (object);
  FpiDeviceYamila *self = (FpiDeviceYamila *) dev;
  Job *job = g_task_get_task_data (G_TASK (result));
  g_autoptr(GError) error = NULL;
  gboolean ok = g_task_propagate_boolean (G_TASK (result), &error);
  if (self->timeout) { g_source_destroy (self->timeout); self->timeout = NULL; }
  if (self->timed_out || fpi_device_action_is_cancelled (dev)) {
    kill_broker (job->process);
    /* io_thread may have read a final result immediately before cancellation.
     * Reap on a separate task before completing the public operation. */
    if (ok) {
      job->mode = 4;
      GTask *reap = g_task_new (dev, NULL, io_complete, NULL);
      Job *next = g_new0 (Job, 1);
      next->process = g_object_ref (job->process); next->mode = 4;
      g_task_set_task_data (reap, next, (GDestroyNotify)job_free);
      g_task_run_in_thread (reap, io_thread);
      g_object_unref (reap);
      return;
    }
    g_clear_error (&error);
    error = g_error_new_literal (G_IO_ERROR, self->timed_out ? G_IO_ERROR_TIMED_OUT : G_IO_ERROR_CANCELLED,
                                 self->timed_out ? "Yamila operation timed out" : "Yamila operation cancelled");
  }
  if (error || job->mode == 3 || job->mode == 4) g_clear_object (&self->process);
  FpiDeviceAction action = fpi_device_get_current_action (dev);
  if (error) {
    self->pending_mode = 0;
    g_clear_pointer (&self->pending_input, g_bytes_unref);
    fpi_device_action_error (dev, g_steal_pointer (&error)); return;
  }
  if (job->mode == 0 && self->pending_mode) {
    guint mode = self->pending_mode;
    g_autoptr(GBytes) input = g_steal_pointer (&self->pending_input);
    self->pending_mode = 0;
    start_io (dev, mode, input);
    return;
  }
  switch (action) {
  case FPI_DEVICE_ACTION_OPEN: fpi_device_open_complete (dev, NULL); break;
  case FPI_DEVICE_ACTION_CLOSE: fpi_device_close_complete (dev, NULL); break;
  case FPI_DEVICE_ACTION_ENROLL: {
    FpPrint *print;
    fpi_device_get_enroll_data (dev, &print);
    gsize size;
    const guint8 *body = g_bytes_get_data (job->output, &size);
    GVariant *data = g_variant_new ("(uss@ay)", 1u, YML_SHA, YML_FORMAT,
                           g_variant_new_fixed_array (G_VARIANT_TYPE_BYTE, body, size, 1));
    fpi_print_set_type (print, FPI_PRINT_RAW);
    g_object_set (print, "fpi-data", data, NULL);
    fpi_print_set_device_stored (print, FALSE);
    fpi_device_enroll_progress (dev, 12, NULL, NULL);
    fpi_device_enroll_complete (dev, g_object_ref (print), NULL);
    break;
  }
  case FPI_DEVICE_ACTION_VERIFY:
    fpi_device_verify_report (dev, job->retry ? FPI_MATCH_ERROR : job->match ? FPI_MATCH_SUCCESS : FPI_MATCH_FAIL,
                               NULL, job->retry ? fpi_device_retry_new (FP_DEVICE_RETRY_GENERAL) : NULL);
    fpi_device_verify_complete (dev, NULL); break;
  case FPI_DEVICE_ACTION_NONE:
  case FPI_DEVICE_ACTION_PROBE:
  case FPI_DEVICE_ACTION_IDENTIFY:
  case FPI_DEVICE_ACTION_CAPTURE:
  case FPI_DEVICE_ACTION_LIST:
  case FPI_DEVICE_ACTION_DELETE:
  case FPI_DEVICE_ACTION_CLEAR_STORAGE:
  default: g_assert_not_reached ();
  }
}
static void timed_out (FpDevice *dev, gpointer data) {
  FpiDeviceYamila *self = data;
  self->timeout = NULL; self->timed_out = TRUE;
  if (self->process) kill_broker (self->process);
}
static void start_io (FpDevice *dev, guint mode, GBytes *input) {
  FpiDeviceYamila *self = (FpiDeviceYamila *) dev;
  GTask *task = g_task_new (dev, NULL, io_complete, NULL);
  Job *job = g_new0 (Job, 1);
  job->process = g_object_ref (self->process); job->mode = mode;
  job->generation = ++self->generation;
  job->input = input ? g_bytes_ref (input) : NULL;
  self->timed_out = FALSE;
  guint seconds = is_virtual (dev) && (mode == 1 || mode == 2) ? 2 : mode == 1 ? 195 : mode == 2 ? 45 : 10;
  self->timeout = fpi_device_add_timeout (dev, seconds * 1000, timed_out, self, NULL);
  g_task_set_task_data (task, job, (GDestroyNotify)job_free);
  g_task_run_in_thread (task, io_thread);
  g_object_unref (task);
}
static gint discover (GUsbDevice *usb) {
  return g_usb_device_get_release (usb) == 0x2003 ? 100 : 0;
}
static void probe (FpDevice *dev) {
  fpi_device_probe_complete (dev, is_virtual (dev) ? "yamila-test-v1" : "2808-06fc-2003-v1", NULL, NULL);
}
static void dev_open (FpDevice *dev) {
  FpiDeviceYamila *self = (FpiDeviceYamila *)dev;
  g_autoptr(GError) error = NULL;
  g_autoptr(GSubprocessLauncher) launcher = g_subprocess_launcher_new (
      G_SUBPROCESS_FLAGS_STDIN_PIPE | G_SUBPROCESS_FLAGS_STDOUT_PIPE | G_SUBPROCESS_FLAGS_STDERR_SILENCE);
  ChildIdentity *identity = g_new0 (ChildIdentity, 1);
  identity->uid = getuid (); identity->gid = getgid (); identity->parent = getpid ();
  if (geteuid () == 0) {
    struct passwd *pw = getpwnam (YML_WORKER_USER);
    if (!pw || pw->pw_uid == 0 || pw->pw_gid == 0 || is_virtual (dev)) {
      g_free (identity);
      self->pending_mode = 0;
      g_clear_pointer (&self->pending_input, g_bytes_unref);
      fpi_device_action_error (dev, fpi_device_error_new_msg (FP_DEVICE_ERROR_GENERAL, "Unprivileged Yamila account required"));
      return;
    }
    identity->uid = pw->pw_uid; identity->gid = pw->pw_gid;
  }
  g_subprocess_launcher_set_child_setup (launcher, child_setup, identity, g_free);
  if (is_virtual (dev)) {
    self->process = g_subprocess_launcher_spawn (launcher, &error, "/usr/bin/python3", "-I", "-B", YML_BROKER,
                          "--mock", fpi_device_get_virtual_env (dev), NULL);
  } else {
    GUsbDevice *usb = fpi_device_get_usb_device (dev);
    g_autofree gchar *bus = g_strdup_printf ("%u", g_usb_device_get_bus (usb));
    g_autofree gchar *address = g_strdup_printf ("%u", g_usb_device_get_address (usb));
    self->process = g_subprocess_launcher_spawn (launcher, &error, "/usr/bin/python3", "-I", "-B", YML_BROKER,
                          "--bus", bus, "--address", address, NULL);
  }
  if (!self->process) {
    self->pending_mode = 0;
    g_clear_pointer (&self->pending_input, g_bytes_unref);
    fpi_device_action_error (dev, g_steal_pointer (&error)); return;
  }
  start_io (dev, 0, NULL);
}
static void dev_close (FpDevice *dev) {
  FpiDeviceYamila *self = (FpiDeviceYamila *)dev;
  if (!self->process) { fpi_device_close_complete (dev, NULL); return; }
  start_io (dev, 3, NULL);
}
static void enroll (FpDevice *dev) {
  FpiDeviceYamila *self = (FpiDeviceYamila *)dev;
  if (!self->process) { self->pending_mode = 1; dev_open (dev); return; }
  start_io (dev, 1, NULL);
}
static void verify (FpDevice *dev) {
  FpiDeviceYamila *self = (FpiDeviceYamila *)dev;
  FpPrint *print;
  g_autoptr(GVariant) data = NULL;
  guint schema;
  FpiPrintType type;
  const gchar *sha, *format;
  g_autoptr(GVariant) bytes = NULL;
  g_autoptr(GBytes) input = NULL;
  fpi_device_get_verify_data (dev, &print);
  g_object_get (print, "fpi-data", &data, "fpi-type", &type, NULL);
  if (type != FPI_PRINT_RAW || !fp_print_compatible (print, dev)) goto invalid;
  if (!data || !g_variant_is_of_type (data, G_VARIANT_TYPE ("(ussay)"))) goto invalid;
  g_variant_get (data, "(u&s&s@ay)", &schema, &sha, &format, &bytes);
  gsize size;
  const guint8 *body = g_variant_get_fixed_array (bytes, &size, 1);
  if (schema != 1 || strcmp (sha, YML_SHA) || strcmp (format, YML_FORMAT) || !valid_record (body, size)) goto invalid;

  input = g_bytes_new (body, size);
  if (!self->process) {
    self->pending_mode = 2; self->pending_input = g_bytes_ref (input);
    dev_open (dev); return;
  }
  start_io (dev, 2, input);
  return;
invalid:
  fpi_device_action_error (dev, fpi_device_error_new_msg (FP_DEVICE_ERROR_DATA_INVALID, "Incompatible Yamila FpPrint schema, DLL or pixel format"));
}
static void cancel (FpDevice *dev) {
  FpiDeviceYamila *self = (FpiDeviceYamila *)dev;
  if (self->process) kill_broker (self->process);
}
static void finalize (GObject *object) {
  FpiDeviceYamila *self = (FpiDeviceYamila *)object;
  if (self->timeout) g_source_destroy (self->timeout);
  if (self->process) { kill_broker (self->process); g_clear_object (&self->process); }
  g_clear_pointer (&self->pending_input, g_bytes_unref);
  G_OBJECT_CLASS (fpi_device_yamila_parent_class)->finalize (object);
}
static const FpIdEntry usb_ids[] = {{.vid = 0x2808, .pid = 0x06fc}, {}};
static void fpi_device_yamila_init (FpiDeviceYamila *self) {}
static void fpi_device_yamila_class_init (FpiDeviceYamilaClass *klass) {
  FpDeviceClass *c = FP_DEVICE_CLASS (klass);
  G_OBJECT_CLASS (klass)->finalize = finalize;
  c->id = "yamila"; c->full_name = "Yamila 2808:06fc prototype";
  c->type = FP_DEVICE_TYPE_USB; c->id_table = usb_ids;
  c->scan_type = FP_SCAN_TYPE_PRESS; c->nr_enroll_stages = 12; c->temp_hot_seconds = -1;
  c->usb_discover = discover; c->probe = probe; c->open = dev_open; c->close = dev_close;
  c->enroll = enroll; c->verify = verify; c->cancel = cancel;
  fpi_device_class_auto_initialize_features (c);
}
/* This type is registered only in the explicitly requested test build. It
 * exercises exactly the same methods, IPC parser and FpPrint implementation. */
typedef struct { FpiDeviceYamila parent; } FpiDeviceYamilaVirtual;
typedef FpiDeviceYamilaClass FpiDeviceYamilaVirtualClass;
GType fpi_device_yamila_virtual_get_type (void);
G_DEFINE_TYPE (FpiDeviceYamilaVirtual, fpi_device_yamila_virtual, fpi_device_yamila_get_type ())
static const FpIdEntry virtual_ids[] = {{.virtual_envvar = "FP_YAMILA_TEST"}, {}};
static void fpi_device_yamila_virtual_init (FpiDeviceYamilaVirtual *self) {}
static void fpi_device_yamila_virtual_class_init (FpiDeviceYamilaVirtualClass *klass) {
  FpDeviceClass *c = FP_DEVICE_CLASS (klass);
  c->id = "yamila_virtual"; c->full_name = "Yamila synthetic IPC test";
  c->type = FP_DEVICE_TYPE_VIRTUAL; c->id_table = virtual_ids; c->usb_discover = NULL;
}
