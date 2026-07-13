# Dispatch priority

AS a grid operator
I WANT dispatch recommendations to prioritize outage risk before service class
SO THAT restoration order stays deterministic.

AC01: outage risk ranks before service class.
AC02: ties break by queued timestamp.
AC03: the dispatch policy module remains the primary implementation surface.
