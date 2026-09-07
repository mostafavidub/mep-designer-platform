import { Container, getRandom } from "@cloudflare/containers";

interface Env {
  CAD_RUNTIME: DurableObjectNamespace<CadRuntime>;
  CAD_SERVICE_TOKEN?: string;
  GIT_COMMIT_SHA?: string;
}

export class CadRuntime extends Container<Env> {
  defaultPort = 8080;
  sleepAfter = "10m";

  constructor(ctx: DurableObjectState<{}>, env: Env) {
    super(ctx, env);
    this.envVars = {
      CAD_ISOLATED_SERVICE: "1",
      GIT_COMMIT_SHA: env.GIT_COMMIT_SHA ?? "UNKNOWN",
    };
  }
}

function sameSecret(left: string, right: string): boolean {
  const encoder = new TextEncoder();
  const a = encoder.encode(left);
  const b = encoder.encode(right);
  let different = a.length ^ b.length;
  const length = Math.max(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    different |= (a[index] ?? 0) ^ (b[index] ?? 0);
  }
  return different === 0;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/design") {
      if (!env.CAD_SERVICE_TOKEN) {
        return Response.json({detail: "CAD edge authentication is not configured"}, {status: 503});
      }
      const supplied = request.headers.get("x-cad-service-token") ?? "";
      if (!sameSecret(supplied, env.CAD_SERVICE_TOKEN)) {
        return Response.json({detail: "unauthorized"}, {status: 401});
      }
    }

    const headers = new Headers(request.headers);
    headers.delete("x-cad-service-token");
    const forwarded = new Request(request, {headers});
    const container = await getRandom(env.CAD_RUNTIME, 2);
    return container.fetch(forwarded);
  },
};
