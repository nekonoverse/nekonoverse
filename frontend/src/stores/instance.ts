import { createSignal } from "solid-js";
import { apiRequest } from "../api/client";

interface InstanceInfo {
  uri: string;
  title: string;
  description: string;
  version: string;
  registrations: boolean;
}

const [instance, setInstance] = createSignal<InstanceInfo | null>(null);
const [instanceLoading, setInstanceLoading] = createSignal(true);

export { instance, instanceLoading };

export function registrationOpen(): boolean {
  return instance()?.registrations ?? false;
}

export async function fetchInstance() {
  setInstanceLoading(true);
  try {
    const info = await apiRequest<InstanceInfo>("/api/v1/instance");
    setInstance(info);
  } catch {
    setInstance(null);
  } finally {
    setInstanceLoading(false);
  }
}
