/* Local development launcher; launches only this checkout's isolated runtime. */
#include <mach-o/dyld.h>
#include <libgen.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
int main(void) {
    char executable[PATH_MAX], project[PATH_MAX], relative[PATH_MAX];
    char python[PATH_MAX], script[PATH_MAX];
    uint32_t size = sizeof executable;
    if (_NSGetExecutablePath(executable, &size) != 0) return 2;
    if (snprintf(relative, sizeof relative, "%s/../../..", dirname(executable)) >= (int)sizeof relative) return 2;
    if (!realpath(relative, project)) return 2;
    if (snprintf(python, sizeof python, "%s/../../work/desktop-env/bin/python", project) >= (int)sizeof python) return 2;
    if (snprintf(script, sizeof script, "%s/launch-local.py", project) >= (int)sizeof script) return 2;
    execl(python, python, script, (char *)NULL);
    perror("OnDemand local runtime");
    return 2;
}
