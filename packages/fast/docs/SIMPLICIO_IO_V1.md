# Simplicio public I/O

Fast owns only `search`: it opens and ranks Mapper context without editing
files or coordinating tasks. The public envelope is `simplicio.io/v1`; internal
mmap, vector and projection formats are private implementation details.

The other operations are owned by Mapper (`understand`), Dev CLI (`change`,
`verify`) and Loop (`run`). Breaking changes require a new major envelope
version and are released with the five-component train.
