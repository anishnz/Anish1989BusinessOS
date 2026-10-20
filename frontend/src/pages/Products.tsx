import { useState } from "react";

import { money } from "../api";
import { useAuth } from "../auth";
import { useData } from "../components/useData";
import type { Page, Product } from "../types";

export default function Products() {
  const [term, setTerm] = useState("");
  const [q, setQ] = useState("");
  const { can } = useAuth();
  const { data, error } = useData<Page<Product>>(`/api/products/?q=${encodeURIComponent(q)}&page_size=100`);
  return (
    <div className="grid">
      <div className="row">
        <h1 style={{ marginRight: "auto" }}>Products</h1>
        {can("products.edit") && <a className="button" href="/admin/catalog/product/">Edit products (classic admin)</a>}
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); setQ(term); }}>
        <input aria-label="Search products" placeholder="Name, code or other name" value={term} onChange={(e) => setTerm(e.target.value)} />
        <button type="submit">Search</button>
      </form>
      {error && <p className="error">{error}</p>}
      <div className="card table-wrap">
        <table>
          <thead><tr><th>Product</th><th>Code</th><th>Category</th><th className="num">Price</th><th>Available</th></tr></thead>
          <tbody>
            {data?.results.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td><td className="muted">{p.sku || "–"}</td><td>{p.category_name || "–"}</td>
                <td className="num">{money(p.price)}{p.unit === "kg" ? "/kg" : p.unit === "pack" ? "/pack" : ""}</td>
                <td>{p.is_available ? "Yes" : <strong>No</strong>}</td>
              </tr>
            ))}
            {data && data.results.length === 0 && <tr><td colSpan={5} className="muted">No products.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
