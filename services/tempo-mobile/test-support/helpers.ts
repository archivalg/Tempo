/** In-memory stand-ins for the secure store and fetch, so the real client code runs unchanged. */
export const mem: Record<string, string> = {}
export const secureStoreMock = {
  AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY: 1,
  getItemAsync: jest.fn(async (k: string) => mem[k] ?? null),
  setItemAsync: jest.fn(async (k: string, v: string) => { mem[k] = v }),
  deleteItemAsync: jest.fn(async (k: string) => { delete mem[k] }),
}
export const json = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, text: async () => (body === undefined ? '' : JSON.stringify(body)) }) as Response
