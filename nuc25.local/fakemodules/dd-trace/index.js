// Stub: dd-trace is not used in self-hosted langfuse deployments.
// This shim satisfies the unconditional ESM import in langfuse/langfuse:3.
const noop = () => {};
const tracer = {
  init: noop, trace: noop, wrap: noop, startSpan: noop,
  scope: () => ({ active: () => null }),
};
module.exports = tracer;
module.exports.default = tracer;
