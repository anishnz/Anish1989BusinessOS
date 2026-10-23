import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { isReady, useAuth } from "./auth";
import Layout from "./components/Layout";
import { homePath } from "./nav";
import Board from "./pages/Board";
import Customers from "./pages/Customers";
import DashboardPage from "./pages/Dashboard";
import Enquiries from "./pages/Enquiries";
import EnquiryDetail from "./pages/EnquiryDetail";
import Inbox from "./pages/Inbox";
import Login from "./pages/Login";
import MfaVerify from "./pages/MfaVerify";
import NewOrder from "./pages/NewOrder";
import Nothing from "./pages/Nothing";
import OrderDetail from "./pages/OrderDetail";
import Orders from "./pages/Orders";
import Products from "./pages/Products";
import Thread from "./pages/Thread";
import Website from "./pages/Website";

function Guard({ needs, children }: { needs?: string; children: React.ReactElement }) {
  const { loading, state, perms, can } = useAuth();
  const location = useLocation();
  if (loading) return <p className="center muted">Loading…</p>;
  if (!state) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (state.mfa.setup_required) {
    window.location.assign(`/account/mfa/setup/?next=${encodeURIComponent("/app" + location.pathname)}`);
    return null;
  }
  if (!isReady(state)) return <Navigate to="/mfa" replace state={{ from: location.pathname }} />;
  if (!perms) return <p className="center muted">Loading…</p>;
  if (needs && !can(needs)) return <Navigate to={homePath(perms.usable)} replace />;
  return children;
}

export default function App() {
  const { perms } = useAuth();
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/mfa" element={<MfaVerify />} />
      <Route element={<Guard><Layout /></Guard>}>
        <Route index element={perms && !perms.usable.includes("reports.view") ? <Navigate to={homePath(perms.usable)} replace /> : <Guard needs="reports.view"><DashboardPage /></Guard>} />
        <Route path="orders" element={<Guard needs="orders.view"><Orders /></Guard>} />
        <Route path="orders/new" element={<Guard needs="orders.create"><NewOrder /></Guard>} />
        <Route path="orders/:id" element={<Guard needs="orders.view"><OrderDetail /></Guard>} />
        <Route path="board" element={<Guard needs="orders.view"><Board /></Guard>} />
        <Route path="inbox" element={<Guard needs="crm.view"><Inbox /></Guard>} />
        <Route path="inbox/:id" element={<Guard needs="crm.view"><Thread /></Guard>} />
        <Route path="products" element={<Guard needs="products.view"><Products /></Guard>} />
        <Route path="enquiries" element={<Guard needs="events.view"><Enquiries /></Guard>} />
        <Route path="enquiries/:id" element={<Guard needs="events.view"><EnquiryDetail /></Guard>} />
        <Route path="customers" element={<Guard needs="crm.view"><Customers /></Guard>} />
        <Route path="website" element={<Guard needs="websites.view"><Website /></Guard>} />
        <Route path="nothing" element={<Nothing />} />
        <Route path="*" element={<Nothing notFound />} />
      </Route>
    </Routes>
  );
}
