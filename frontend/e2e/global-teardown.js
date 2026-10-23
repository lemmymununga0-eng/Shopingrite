import { stopBackend, stopFakeFlutterwave } from "./helpers.js";

export default async function globalTeardown() {
  stopBackend();
  stopFakeFlutterwave();
}
