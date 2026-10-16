import { resetE2eData, startBackend } from "./helpers.js";

export default async function globalSetup() {
  resetE2eData();
  await startBackend();
}
