"""Synthetic exact-wheel evidence for host-independent release-gate tests."""
from scripts.pyyaml_runtime import manifest


def add_yaml_evidence(report, system):
    review = manifest()
    wheel = review['wheels'][system]
    prefix = 'C:/Python' if system == 'win32' else '/Python'
    site = prefix + '/lib/site-packages/'
    evidence = dict(version=review['version'], libyaml_version=review['libyaml_version'],
        reviewed=True, platform=system, architecture=wheel['architecture'],
        extension=dict(path=wheel['extension_path'], source=site + wheel['extension_path'], sha256=wheel['extension_sha256']),
        python_modules={name: dict(source=site + item['path'], sha256=item['sha256'])
                        for name, item in review['python_modules'].items()},
        installed_license=dict(source=site + 'pyyaml-6.0.3.dist-info/licenses/LICENSE',
                               sha256=review['notices']['PyYAML-LICENSE.txt']['sha256']))
    report['runtime'].update(prefix=prefix, pyyaml=evidence)
    report['collected_dependencies'] = [dict(destination=name, type='PYMODULE', **record)
                                       for name, record in evidence['python_modules'].items()]
    path = ('_internal/' if system != 'darwin' else 'Contents/Frameworks/') + wheel['extension_path']
    report['binaries'].append(dict(path=path, sha256=wheel['extension_sha256'],
        format='PE' if system == 'win32' else 'Mach-O', origin_hash_verified=True,
        origin_candidates=[dict(source=evidence['extension']['source'], sha256=wheel['extension_sha256'], type='EXTENSION')],
        imports=[]))
    report['files'].append(dict(path=path, sha256=wheel['extension_sha256']))
    if system == 'darwin':
        report['symlinks'].append(dict(path='Contents/Resources/yaml', target='../Frameworks/yaml'))
    return evidence
