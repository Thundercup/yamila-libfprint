/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include <libfprint/fprint.h>
#include <glib/gstdio.h>
#include <sys/stat.h>
#include <string.h>
#include <unistd.h>

static gchar *directory, *scenario_file;
static FpContext *context;
static FpDevice *device;
static void scenario (const gchar *name) {
  g_autoptr(GError) error = NULL;
  g_assert_true (g_file_set_contents (scenario_file, name, -1, &error));
  g_assert_no_error (error);
}
static void open_device (void) {
  g_autoptr(GError) error = NULL;
  g_assert_true (fp_device_open_sync (device, NULL, &error)); g_assert_no_error (error);
}
static void close_device (void) {
  g_autoptr(GError) error = NULL;
  g_assert_true (fp_device_close_sync (device, NULL, &error)); g_assert_no_error (error);
}
static guint progress_count, ticks;
static void progress (FpDevice *dev, gint completed, FpPrint *print, gpointer unused, GError *error) {
  g_assert_no_error (error);
  g_assert_cmpint (completed, ==, ++progress_count);
}
static FpPrint *enroll (void) {
  g_autoptr(GError) error = NULL;
  g_autoptr(FpPrint) blank = g_object_ref_sink (fp_print_new (device));
  fp_print_set_finger (blank, FP_FINGER_RIGHT_MIDDLE);
  progress_count = 0;
  FpPrint *print = fp_device_enroll_sync (device, blank, NULL, progress, NULL, &error);
  g_assert_no_error (error); g_assert_nonnull (print);
  g_assert_cmpuint (progress_count, ==, 12);
  g_assert_false (fp_print_get_device_stored (print));
  g_test_message ("Print identity driver=%s id=%s; device=%s/%s", fp_print_get_driver (print), fp_print_get_device_id (print), fp_device_get_driver (device), fp_device_get_device_id (device));
  return print;
}
static void assert_match (FpPrint *print, gboolean expected) {
  g_autoptr(GError) error = NULL;
  gboolean match = !expected;
  g_assert_true (fp_device_verify_sync (device, print, NULL, NULL, NULL, &match, NULL, &error));
  g_assert_no_error (error); g_assert_cmpint (match, ==, expected);
}
static void test_roundtrip (void) {
  scenario ("normal"); open_device ();
  g_autoptr(FpPrint) print = enroll ();
  g_autofree guchar *data = NULL; gsize size;
  g_autoptr(GError) error = NULL;
  g_assert_true (fp_print_serialize (print, &data, &size, &error)); g_assert_no_error (error);
  g_autoptr(FpPrint) copy = fp_print_deserialize (data, size, &error); g_assert_no_error (error);
  g_assert_true (fp_print_equal (print, copy));
  assert_match (copy, TRUE);
  close_device ();
  /* The backend has no template directory: standard callers own persistence.
   * Exercise a private save/load/delete without touching fprintd or old AEAD. */
  g_autofree gchar *path = g_build_filename (directory, "synthetic.fpprint", NULL);
  g_assert_true (g_file_set_contents_full (path, (gchar *)data, size, G_FILE_SET_CONTENTS_CONSISTENT, 0600, &error));
  struct stat st; g_assert_cmpint (g_stat (path, &st), ==, 0); g_assert_cmpint (st.st_mode & 0777, ==, 0600);
  g_clear_object (&copy);
  g_autofree gchar *saved = NULL; gsize saved_size;
  g_assert_true (g_file_get_contents (path, &saved, &saved_size, &error));
  copy = fp_print_deserialize ((guchar *)saved, saved_size, &error); g_assert_no_error (error);
  open_device (); assert_match (copy, TRUE); close_device ();
  g_assert_cmpint (g_unlink (path), ==, 0);
  scenario ("no-match"); open_device (); assert_match (copy, FALSE); close_device ();
}
static void test_invalid (void) {
  scenario ("normal"); open_device ();
  g_autoptr(FpPrint) print = enroll ();
  g_object_set (print, "fpi-data", g_variant_new_string ("old-AEAD-is-not-FpPrint"), NULL);
  g_autoptr(GError) error = NULL; gboolean match = TRUE;
  g_assert_false (fp_device_verify_sync (device, print, NULL, NULL, NULL, &match, NULL, &error));
  g_assert_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_DATA_INVALID);
  g_clear_error (&error);
  g_clear_object (&print); print = enroll (); /* invalid print did not poison device */
  GVariant *wrong = g_variant_new ("(uss@ay)", 1u, "wrong-DLL", "gray8-shift2-64x80-v1",
                        g_variant_new_fixed_array (G_VARIANT_TYPE_BYTE, "123456789012", 12, 1));
  g_object_set (print, "fpi-data", wrong, NULL);
  g_assert_false (fp_device_verify_sync (device, print, NULL, NULL, NULL, &match, NULL, &error));
  g_assert_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_DATA_INVALID);
  close_device ();
}
static gboolean cancel_cb (gpointer data) { g_cancellable_cancel (data); return G_SOURCE_REMOVE; }
static gboolean tick_cb (gpointer data) { ticks++; return G_SOURCE_CONTINUE; }
static void test_cancel_scenario (gconstpointer data) {
  scenario (data); open_device ();
  g_autoptr(GCancellable) cancel = g_cancellable_new ();
  g_autoptr(FpPrint) blank = g_object_ref_sink (fp_print_new (device));
  g_autoptr(GError) error = NULL;
  ticks = 0;
  guint tick_id = g_timeout_add (5, tick_cb, NULL);
  g_timeout_add (120, cancel_cb, cancel);
  gint64 start = g_get_monotonic_time ();
  g_autoptr(FpPrint) print = fp_device_enroll_sync (device, blank, cancel, NULL, NULL, &error);
  g_assert_null (print); g_assert_error (error, G_IO_ERROR, G_IO_ERROR_CANCELLED);
  g_assert_cmpint (g_get_monotonic_time ()-start, <, 2000000);
  g_assert_cmpuint (ticks, >, 2); g_source_remove (tick_id);
  scenario ("normal"); g_clear_object (&print); print = enroll (); close_device ();
}
static void test_failure_scenario (gconstpointer data) {
  scenario (data); open_device ();
  g_autoptr(FpPrint) blank = g_object_ref_sink (fp_print_new (device));
  g_autoptr(GError) error = NULL;
  g_autoptr(FpPrint) print = fp_device_enroll_sync (device, blank, NULL, NULL, NULL, &error);
  g_assert_null (print); g_assert_nonnull (error);
  g_clear_error (&error);
  /* A new explicit request may create a new broker; the failed request is
   * never replayed. The same malformed scenario still fails closed. */
  print = fp_device_enroll_sync (device, blank, NULL, NULL, NULL, &error);
  g_assert_null (print); g_assert_nonnull (error);
  scenario ("normal"); print = enroll (); close_device ();
}
static void test_timeout (void) {
  scenario ("hang"); open_device ();
  g_autoptr(FpPrint) blank = g_object_ref_sink (fp_print_new (device));
  g_autoptr(GError) error = NULL;
  gint64 start = g_get_monotonic_time ();
  g_autoptr(FpPrint) print = fp_device_enroll_sync (device, blank, NULL, NULL, NULL, &error);
  g_assert_null (print); g_assert_error (error, G_IO_ERROR, G_IO_ERROR_TIMED_OUT);
  g_assert_cmpint (g_get_monotonic_time ()-start, <, 4000000);
  close_device ();
}
static void test_verify_cancel (void) {
  scenario ("normal"); open_device (); g_autoptr(FpPrint) print = enroll (); close_device ();
  scenario ("late"); open_device ();
  g_autoptr(GCancellable) cancel = g_cancellable_new ();
  g_timeout_add (120, cancel_cb, cancel);
  g_autoptr(GError) error = NULL;
  gboolean match = TRUE;
  g_assert_false (fp_device_verify_sync (device, print, cancel, NULL, NULL, &match, NULL, &error));
  g_assert_error (error, G_IO_ERROR, G_IO_ERROR_CANCELLED);
  g_assert_false (match); close_device ();
}
static void test_foreign_print (void) {
  scenario ("normal"); open_device ();
  g_autoptr(FpPrint) print = enroll ();
  g_autoptr(GVariant) data = NULL;
  gint type;
  g_object_get (print, "fpi-data", &data, "fpi-type", &type, NULL);
  g_autoptr(FpPrint) foreign = g_object_ref_sink (g_object_new (FP_TYPE_PRINT,
    "driver", "foreign-driver", "device-id", "foreign-device", "fpi-type", type,
    "fpi-data", data, NULL));
  g_autoptr(GError) error = NULL; gboolean match = TRUE;
  g_assert_false (fp_device_verify_sync (device, foreign, NULL, NULL, NULL, &match, NULL, &error));
  g_assert_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_DATA_INVALID);
  g_assert_false (match); close_device ();
}
static void async_ready (GObject *source, GAsyncResult *result, gpointer data) {
  GAsyncResult **pending = data;
  g_assert_null (*pending); *pending = g_object_ref (result);
}
static void test_async_busy (void) {
  scenario ("hang"); open_device ();
  g_autoptr(FpPrint) first = g_object_ref_sink (fp_print_new (device));
  g_autoptr(FpPrint) second = g_object_ref_sink (fp_print_new (device));
  g_autoptr(GCancellable) cancel = g_cancellable_new ();
  g_autoptr(GAsyncResult) pending = NULL;
  fp_device_enroll (device, first, cancel, NULL, NULL, NULL, async_ready, &pending);
  g_autoptr(GError) error = NULL;
  g_autoptr(FpPrint) print = fp_device_enroll_sync (device, second, NULL, NULL, NULL, &error);
  g_assert_null (print); g_assert_error (error, FP_DEVICE_ERROR, FP_DEVICE_ERROR_BUSY);
  g_clear_error (&error); g_cancellable_cancel (cancel);
  while (!pending) g_main_context_iteration (NULL, TRUE);
  print = fp_device_enroll_finish (device, pending, &error);
  g_assert_null (print); g_assert_error (error, G_IO_ERROR, G_IO_ERROR_CANCELLED);
  close_device ();
}
static void cancel_on_progress (FpDevice *dev, gint completed, FpPrint *print, gpointer data, GError *error) {
  if (completed == 11) g_cancellable_cancel (data);
}
static void test_cancel_queued_success (void) {
  scenario ("normal"); open_device ();
  g_autoptr(GCancellable) cancel = g_cancellable_new ();
  g_autoptr(FpPrint) blank = g_object_ref_sink (fp_print_new (device));
  g_autoptr(GError) error = NULL;
  g_autoptr(FpPrint) print = fp_device_enroll_sync (device, blank, cancel, cancel_on_progress, cancel, &error);
  g_assert_null (print); g_assert_error (error, G_IO_ERROR, G_IO_ERROR_CANCELLED);
  close_device ();
}
static void test_private_main_context (void) {
  scenario ("hang");
  g_autoptr(GMainContext) main_context = g_main_context_new ();
  g_main_context_push_thread_default (main_context);
  g_autoptr(GAsyncResult) pending = NULL;
  g_autoptr(GError) error = NULL;
  fp_device_open (device, NULL, async_ready, &pending);
  while (!pending) g_main_context_iteration (main_context, TRUE);
  g_assert_true (fp_device_open_finish (device, pending, &error)); g_assert_no_error (error);
  g_clear_object (&pending);
  g_autoptr(FpPrint) blank = g_object_ref_sink (fp_print_new (device));
  fp_device_enroll (device, blank, NULL, NULL, NULL, NULL, async_ready, &pending);
  while (!pending) g_main_context_iteration (main_context, TRUE);
  g_autoptr(FpPrint) print = fp_device_enroll_finish (device, pending, &error);
  g_assert_null (print); g_assert_error (error, G_IO_ERROR, G_IO_ERROR_TIMED_OUT);
  g_clear_error (&error); g_clear_object (&pending);
  fp_device_close (device, NULL, async_ready, &pending);
  while (!pending) g_main_context_iteration (main_context, TRUE);
  g_assert_true (fp_device_close_finish (device, pending, &error)); g_assert_no_error (error);
  g_main_context_pop_thread_default (main_context);
}
static void test_exclusive (void) {
  scenario ("normal"); open_device ();
  g_autoptr(FpContext) other = fp_context_new (); fp_context_enumerate (other);
  GPtrArray *devices = fp_context_get_devices (other); g_assert_cmpuint (devices->len, ==, 1);
  FpDevice *second = g_ptr_array_index (devices, 0);
  g_autoptr(GError) error = NULL;
  g_assert_false (fp_device_open_sync (second, NULL, &error)); g_assert_nonnull (error);
  close_device (); g_clear_error (&error);
  g_assert_true (fp_device_open_sync (second, NULL, &error)); g_assert_no_error (error);
  g_assert_true (fp_device_close_sync (second, NULL, &error)); g_assert_no_error (error);
}
int main (int argc, char **argv) {
  g_test_init (&argc, &argv, NULL);
  const gchar *abandon = g_getenv ("YAMILA_ABANDON_DIR");
  directory = abandon ? g_strdup (abandon) : g_dir_make_tmp ("yamila-fp-test-XXXXXX", NULL); g_assert_nonnull (directory);
  scenario_file = g_build_filename (directory, "scenario", NULL);
  g_setenv ("FP_YAMILA_TEST", directory, TRUE);
  g_setenv ("FP_DRIVERS_ALLOWLIST", "yamila_virtual", TRUE);
  context = fp_context_new (); fp_context_enumerate (context);
  GPtrArray *devices = fp_context_get_devices (context);
  g_assert_cmpuint (devices->len, ==, 1); device = g_ptr_array_index (devices, 0);
  g_assert_cmpstr (fp_device_get_driver (device), ==, "yamila_virtual");
  g_assert_true (fp_device_has_feature (device, FP_DEVICE_FEATURE_VERIFY));
  g_assert_false (fp_device_has_feature (device, FP_DEVICE_FEATURE_STORAGE));
  if (abandon) { open_device (); _exit (0); }
  g_test_add_func ("/yamila/foreign-print", test_foreign_print);
  g_test_add_func ("/yamila/async-busy", test_async_busy);
  g_test_add_func ("/yamila/cancel-queued-success", test_cancel_queued_success);
  g_test_add_func ("/yamila/private-main-context", test_private_main_context);
  g_test_add_func ("/yamila/timeout", test_timeout);
  g_test_add_func ("/yamila/verify-cancel", test_verify_cancel);
  g_test_add_func ("/yamila/roundtrip", test_roundtrip);
  g_test_add_func ("/yamila/incompatible-template", test_invalid);
  g_test_add_data_func ("/yamila/cancel", "hang", test_cancel_scenario);
  g_test_add_data_func ("/yamila/late-success", "late", test_cancel_scenario);
  g_test_add_data_func ("/yamila/crash-recover", "crash", test_failure_scenario);
  g_test_add_data_func ("/yamila/malformed-recover", "malformed", test_failure_scenario);
  g_test_add_func ("/yamila/exclusive", test_exclusive);
  int result = g_test_run ();
  g_object_unref (context);
  g_autofree gchar *lock = g_build_filename (directory, "device.lock", NULL);
  g_unlink (scenario_file); g_unlink (lock); g_rmdir (directory);
  g_free (scenario_file); g_free (directory);
  return result;
}
