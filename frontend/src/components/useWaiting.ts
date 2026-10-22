import { useEffect, useState } from "react";

import { api } from "../api";
import type { WaitingChat } from "../types";

/** Chats the AI handed to staff that nobody picked up yet (task 2.5), checked every 30 seconds. */
export function useWaiting(enabled: boolean): WaitingChat[] {
  const [chats, setChats] = useState<WaitingChat[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let stop = false;
    const load = () =>
      api<{ count: number; results: WaitingChat[] }>("/api/ai/waiting/")
        .then((page) => !stop && setChats(page.results))
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 30000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [enabled]);
  return chats;
}
