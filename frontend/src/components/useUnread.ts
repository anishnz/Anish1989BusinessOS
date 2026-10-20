import { useEffect, useState } from "react";

import { api } from "../api";
import type { Page, Conversation } from "../types";

/** Number of open conversations with unread messages, checked every 30 seconds. */
export function useUnread(enabled: boolean): number {
  const [count, setCount] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let stop = false;
    const load = () =>
      api<Page<Conversation>>("/api/inbox/conversations/?status=open&unread=true&page_size=1")
        .then((page) => !stop && setCount(page.count))
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 30000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [enabled]);
  return count;
}
