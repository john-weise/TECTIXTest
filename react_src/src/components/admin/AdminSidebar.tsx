// src/components/admin/AdminSidebar.tsx
import React from "react";

export type AdminSection =
  | "users"
  | "about"
  | "logs"
  | "portfolio"
  | "policies"
  | "emass"; 

type Props = {
  section: AdminSection;
  onChange: (s: AdminSection) => void;
};

export default function AdminSidebar({ section, onChange }: Props) {
  const Item = ({
    name,
    label,
  }: {
    name: AdminSection;
    label: string;
  }) => (
    <li
      className={`admin-nav-item ${section === name ? "active" : ""}`}
      onClick={() => onChange(name)}
      role="button"
      tabIndex={0}
      aria-current={section === name ? "page" : undefined}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onChange(name);
      }}
    >
      {label}
    </li>
  );

  return (
    <aside className="admin-sidebar" aria-label="Admin Sections">
      <div className="admin-sidebar-title">Admin</div>
      <ul className="admin-nav">
        <Item name="users" label="Manage Users" />
        <Item name="policies" label="Scan Policy Management" />
        <Item name="logs" label="View Logs" />
        <Item name="portfolio" label="Manage Monitoring Portfolio" />
        <Item name="emass" label="eMASS Connection Management" /> 
        <Item name="about" label="About" />
      </ul>
    </aside>
  );
}

export {};
