# Build context is the nuc25.local repo root (see compose `context: .`), not the
# ragflow/ submodule directly — this build reaches into two submodule subtrees
# (web/ and rag/flow/cleanup/) that a context scoped to just this directory
# couldn't see. Every COPY source path below is prefixed `ragflow/`.
ARG RAGFLOW_BASE_IMAGE

FROM node:20 AS web-builder
WORKDIR /ragflow
COPY ragflow/web/package.json ragflow/web/package-lock.json ragflow/web/.npmrc ./web/
RUN cd web && NODE_OPTIONS="--max-old-space-size=8192" npm install
COPY ragflow/web web
COPY ragflow/docs docs
RUN cd web && NODE_OPTIONS="--max-old-space-size=8192" VITE_BUILD_SOURCEMAP=false VITE_MINIFY=esbuild npm run build

FROM ${RAGFLOW_BASE_IMAGE}
COPY --from=web-builder /ragflow/web/dist /ragflow/web/dist
COPY ragflow/rag/flow/cleanup /ragflow/rag/flow/cleanup
