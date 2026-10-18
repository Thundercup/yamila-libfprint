/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Exec the fixed sibling worker, independent of source or build directory. */
#include <sys/prctl.h>
#include <sys/resource.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <unistd.h>
int main (int argc, char **argv) {
  const char *expected = getenv ("YML_ENGINE_PARENT_PID");
  struct rlimit core = {0, 0}, inherited_core;
  char worker[PATH_MAX];
  if (argc != 2 || geteuid () == 0 || !expected ||
      strtol (expected, NULL, 10) != getppid ()) return 77;
  if (prctl (PR_SET_PDEATHSIG, SIGKILL) ||
      prctl (PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) ||
      prctl (PR_SET_DUMPABLE, 0) || getrlimit (RLIMIT_CORE, &inherited_core) ||
      ((inherited_core.rlim_cur || inherited_core.rlim_max) && setrlimit (RLIMIT_CORE, &core)) ||
      strtol (expected, NULL, 10) != getppid ()) return 78;
  ssize_t length = readlink ("/proc/self/exe", worker, sizeof (worker) - 1);
  if (length < 0 || length >= (ssize_t)sizeof(worker)-1) return 79;
  worker[length] = '\0';
  char *slash = strrchr (worker, '/');
  if (!slash || (size_t)(slash-worker)+sizeof("/native-worker") > sizeof(worker)) return 79;
  strcpy (slash, "/native-worker");
  execl (worker, worker, argv[1], (char *)NULL);
  return 79;
}
