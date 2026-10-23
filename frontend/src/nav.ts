/** Menu items and the permission each one needs. Items the person cannot use are not shown. */
export interface NavItem {
  to: string;
  label: string;
  needs: string;
}

export const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", needs: "reports.view" },
  { to: "/orders", label: "Orders", needs: "orders.view" },
  { to: "/board", label: "Board", needs: "orders.view" },
  { to: "/inbox", label: "Inbox", needs: "crm.view" },
  { to: "/products", label: "Products", needs: "products.view" },
  { to: "/enquiries", label: "Enquiries", needs: "events.view" },
  { to: "/customers", label: "Customers", needs: "crm.view" },
  { to: "/website", label: "Website", needs: "websites.view" },
];

export function visibleNav(usable: string[]): NavItem[] {
  const allowed = new Set(usable);
  return NAV.filter((item) => allowed.has(item.needs));
}

/** Where to go after login: the first page the person can use. */
export function homePath(usable: string[]): string {
  return visibleNav(usable)[0]?.to ?? "/nothing";
}
