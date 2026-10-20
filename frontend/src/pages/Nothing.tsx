export default function Nothing({ notFound = false }: { notFound?: boolean }) {
  return (
    <div className="card">
      <h1>{notFound ? "Page not found" : "Nothing to show yet"}</h1>
      <p className="muted">
        {notFound
          ? "This page does not exist."
          : "Your roles do not include any of these screens yet. Ask your System Admin to give you a role, or use the classic admin."}
      </p>
    </div>
  );
}
