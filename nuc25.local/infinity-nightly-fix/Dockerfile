# TEMPORARY (2026-07-12): infiniflow/infinity:nightly-x64-v4 has the JsonTermT
# variable-length fix (upstream commit 6fcc896, merged 2026-06-22) that v0.7.0
# lacks, but the nightly image is missing libatomic1 -- the newly-compiled
# binary links against it (v0.7.0's binary doesn't) and the image build never
# installs it, so /usr/bin/infinity fails immediately with
# "error while loading shared libraries: libatomic.so.1: cannot open shared
# object file". This overlay just adds the missing package. Remove once a
# tagged release ships with both the JsonTermT fix and a working image build.
# See nuc25.local/CLAUDE.md's Infinity crash section for the full incident.
FROM infiniflow/infinity:nightly-x64-v4
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 && rm -rf /var/lib/apt/lists/*
