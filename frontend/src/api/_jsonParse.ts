/**
 * v2.26-WP02 (Bucket C2 from v2.18): single seam for typed JSON parsing.
 *
 * The dom-lib types Response.json() as Promise<any>, which silently absorbs
 * shape drift between backend and frontend. parseJson<T> narrows the return
 * to unknown before casting to T, giving an explicit cast site (greppable),
 * and accepts an optional runtime guard for sites where shape divergence
 * has real cost.
 *
 * Rule (yy): a structural seam that makes future guard adoption mechanical
 * is worth shipping even without immediate guards.
 */
export async function parseJson<T>(
  res: Response,
  guard?: (x: unknown) => x is T,
): Promise<T> {
  const body = (await res.json()) as unknown;
  if (guard && !guard(body)) {
    throw new Error("parseJson: response body failed runtime guard");
  }
  return body as T;
}
