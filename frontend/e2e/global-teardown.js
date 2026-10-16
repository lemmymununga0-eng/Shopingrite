import { stopBackend } from "./helpers.js";

export default async function globalTeardown() {
  stopBackend();
}
