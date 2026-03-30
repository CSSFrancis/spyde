SpyDE
=====

SpyDE is a python program built on top of Hyperspy.  It is designed to help with the visualization and analysis
of data from (Direct Electron) DE cameras and other electron microscopy detectors.


Download
--------

Pre-built applications are available on the [Releases](https://github.com/directelectron/spyde/releases) page.

| Platform | Download |
|----------|----------|
| Windows  | `SpyDE.exe` — run directly, no install needed |
| macOS    | `SpyDE.dmg` — open and drag SpyDE to Applications |
| Linux    | `SpyDE.AppImage` — `chmod +x SpyDE.AppImage && ./SpyDE.AppImage` |


Installation (developers)
--------------------------

As spyde isn't (yet) hosted on PyPI, install directly from the repository:

```bash
pip install git+https://github.com/directelectron/spyde.git
```

Once installed, SpyDE can be launched from the command line:

```bash
spyde
```


Releasing a new version
------------------------

Push a version tag to trigger the CI build matrix (Windows, macOS, Linux) and
automatically publish a GitHub Release with all three platform artifacts:

```bash
git tag v0.1.0
git push origin v0.1.0
```
