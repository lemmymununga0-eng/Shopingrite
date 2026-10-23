import { resetE2eData, startBackend, startFakeFlutterwave } from "./helpers.js";

export default async function globalSetup() {
  resetE2eData();
  await startFakeFlutterwave();
  await startBackend();
}
