// src/components/admin/PortfolioPanel.tsx
import React, { useEffect, useState, useRef } from "react";
import {
  SystemSummary,
  AutodiscoveryItem,
  AddSystemBatchInput,
} from "../../types/admin";
import AutodiscoverySection from "./AutodiscoverySection";
import PortfolioSection from "./PortfolioSection";

/**
 * PortfolioPanel
 *
 * Container component that:
 *  - Fetches / manages state for portfolio systems and autodiscovery
 *  - Owns all CRUD + bulk-add logic
 *  - Delegates rendering to AutodiscoverySection and PortfolioSection
 */
export default function PortfolioPanel() {
  /** -------------------- Portfolio table state ------------------------- */
  const [systems, setSystems] = useState<SystemSummary[]>([]);
  const [systemsLoading, setSystemsLoading] = useState<boolean>(false);
  const [systemsError, setSystemsError] = useState<string>("");

  /** -------------------- Add form state (manual add) ------------------- */
  const [showAdd, setShowAdd] = useState<boolean>(false);
  const [newSystemId, setNewSystemId] = useState<string>("");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [submitError, setSubmitError] = useState<string>("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  /** Destructive toggles in header */
  const [purgeOnDelete, setPurgeOnDelete] = useState<boolean>(true);
  const [purgeOnUnset, setPurgeOnUnset] = useState<boolean>(false);

  /** -------------------- Autodiscovery state --------------------------- */
  const [autoItems, setAutoItems] = useState<AutodiscoveryItem[]>([]);
  const [autoLoading, setAutoLoading] = useState<boolean>(false);
  const [autoError, setAutoError] = useState<string>("");

  // Per-row CSV selection for autodiscovered systems (keyed by system_id)
  const [autoCsvMap, setAutoCsvMap] = useState<Record<number, File | null>>({});

  /** Fast lookup for "already in portfolio" checks. */
  const portfolioIdSet = new Set(systems.map((s) => s.system_id));

  /** -------------------- Data fetchers --------------------------------- */

  /**
   * Fetch and populate the systems table.
   * The backend returns SystemSummary rows with fields including:
   *   system_id, has_csv (bool), scan_policy (string|null), time_added, last_scanned
   */
  const fetchSystems = async () => {
    setSystemsLoading(true);
    setSystemsError("");
    try {
      const response = await fetch("/api/admin/systems", { credentials: "include" });
      if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
          const j = await response.json();
          if ((j as any)?.error) message = (j as any).error;
        } catch {
          /* ignore */
        }
        throw new Error(message);
      }
      const data: SystemSummary[] = await response.json();
      setSystems(data);
    } catch (err: any) {
      setSystemsError(`Failed to load systems: ${err?.message ?? String(err)}`);
    } finally {
      setSystemsLoading(false);
    }
  };

  /**
   * Query autodiscovery API for systems visible in fixtures and their policy status.
   * Shape: [{ system_id, has_policy, policies: [name...] }, ...]
   */
  const fetchAutodiscovery = async () => {
    setAutoLoading(true);
    setAutoError("");
    try {
      const res = await fetch("/api/autodiscovery", { credentials: "include" });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const j = await res.json();
          if ((j as any)?.error) msg = (j as any).error;
        } catch {
          /* no-op */
        }
        throw new Error(msg);
      }
      const data: AutodiscoveryItem[] = await res.json();
      setAutoItems(data);
      // Reset per-row file map (avoid stale files when reloading)
      setAutoCsvMap({});
    } catch (err: any) {
      setAutoError(`Autodiscovery failed: ${err?.message ?? String(err)}`);
    } finally {
      setAutoLoading(false);
    }
  };

  useEffect(() => {
    void fetchSystems();
  }, []);

  /** -------------------- CRUD helpers ---------------------------------- */

  /**
   * Create/Upsert a system in the portfolio (single).
   * Optionally upload a CSV file immediately after creation.
   *
   * Backend supports both:
   *   - single payload: { system_id, csv_path }
   *   - batch payload:  { items: [{ system_id, csv_path }, ...] }
   *
   * Here we use the single form for per-row add.
   */
  const createSystemWithOptionalCsv = async (systemId: number, file: File | null) => {
    // 1) Create/Upsert system (single style; batch-compatible backend)
    {
      const res = await fetch("/api/admin/systems", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ system_id: systemId, csv_path: null }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error((j as any)?.error || `Create system failed (HTTP ${res.status})`);
      }
    }

    // 2) Upload CSV if provided
    if (file) {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`/api/admin/systems/${encodeURIComponent(systemId)}/csv`, {
        method: "POST",
        credentials: "include",
        body: form,
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error((j as any)?.error || `Upload CSV failed (HTTP ${res.status})`);
      }
    }
  };

  /** Manual add form submit */
  const onAddSystem = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitError("");
    const idNum = Number(newSystemId);
    if (!newSystemId || isNaN(idNum) || idNum < 0) {
      setSubmitError("Please enter a valid non-negative numeric System ID.");
      return;
    }

    setSubmitting(true);
    try {
      await createSystemWithOptionalCsv(idNum, csvFile);
      // Reset UI and refresh
      setNewSystemId("");
      setCsvFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setShowAdd(false);
      await fetchSystems();
    } catch (err: any) {
      setSubmitError(err?.message || String(err));
    } finally {
      setSubmitting(false);
    }
  };

  /** Delete a system after confirmation (optional purge configured via toggle). */
  const onDeleteSystem = async (systemId: number) => {
    const confirmed = window.confirm(`Delete system ${systemId}? This cannot be undone.`);
    if (!confirmed) return;

    try {
      const url = `/api/admin/systems/${encodeURIComponent(
        systemId
      )}?purge_file=${purgeOnDelete ? "1" : "0"}`;
      const res = await fetch(url, { method: "DELETE", credentials: "include" });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error((j as any)?.error || `Delete failed (HTTP ${res.status})`);
      // Optimistic UI
      setSystems((prev) => prev.filter((s) => s.system_id !== systemId));
    } catch (err: any) {
      alert(`Delete failed: ${err?.message ?? String(err)}`);
    }
  };

  /** Unset a system's CSV with optional purge (toggle). */
  const onUnsetCsv = async (systemId: number) => {
    const confirmed = window.confirm(
      `Unset CSV mapping for system ${systemId}?` +
        (purgeOnUnset ? " The file on disk will also be removed if present." : "")
    );
    if (!confirmed) return;

    try {
      const url = `/api/admin/systems/${encodeURIComponent(
        systemId
      )}/csv?purge_file=${purgeOnUnset ? "1" : "0"}`;
      const res = await fetch(url, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csv_path: null }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error((j as any)?.error || `Unset CSV failed (HTTP ${res.status})`);
      // Replace row with server copy
      setSystems((prev) => prev.map((s) => (s.system_id === systemId ? (j as SystemSummary) : s)));
    } catch (err: any) {
      alert(`Unset CSV failed: ${err?.message ?? String(err)}`);
    }
  };

  /** Add a single autodiscovered system (per-row action). */
  const onAddAutodiscovered = async (systemId: number) => {
    const file = autoCsvMap[systemId] ?? null;
    try {
      await createSystemWithOptionalCsv(systemId, file);
      // Refresh portfolio table and autodiscovery (so "already in portfolio" flips)
      await fetchSystems();
      await fetchAutodiscovery();
    } catch (err: any) {
      alert(`Add failed: ${err?.message ?? String(err)}`);
    }
  };

  /**
   * Bulk add selected autodiscovered systems using the new batch-capable endpoint.
   *
   * AutodiscoverySection will:
   *  - freeze the count
   *  - show the full-screen overlay
   *  - call this with the IDs it has selected
   *
   * If anything fails, throw an Error with a human-readable summary so the section
   * can show a clean status message.
   */
  const onBulkAddSelected = async (systemIds: number[]): Promise<void> => {
    // De-duplicate + ignore anything already in the portfolio (paranoia / safety).
    const uniqueIds = Array.from(new Set(systemIds));
    const idsToCreate = uniqueIds.filter((id) => !portfolioIdSet.has(id));

    if (idsToCreate.length === 0) {
      // Nothing to do; no error.
      return;
    }

    // 1) Batch-create systems (no CSV) via new batch shape.
    {
      const payload: AddSystemBatchInput = {
        items: idsToCreate.map((id) => ({
          system_id: id,
          csv_path: null,
        })),
      };

      const res = await fetch("/api/admin/systems", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg =
          (j as any)?.error ||
          `Batch add failed during create step (HTTP ${res.status}).`;
        throw new Error(msg);
      }
    }

    // 2) Upload CSVs (if any) for those systems
    const uploadFailures: string[] = [];

    for (const systemId of idsToCreate) {
      const file = autoCsvMap[systemId];
      if (!file) continue;

      try {
        const form = new FormData();
        form.append("file", file);
        const res = await fetch(
          `/api/admin/systems/${encodeURIComponent(systemId)}/csv`,
          {
            method: "POST",
            credentials: "include",
            body: form,
          }
        );
        const j = await res.json().catch(() => ({}));
        if (!res.ok) {
          const msg =
            (j as any)?.error ||
            `Upload CSV failed for system ${systemId} (HTTP ${res.status})`;
          uploadFailures.push(msg);
        }
      } catch (err: any) {
        uploadFailures.push(
          `Upload CSV failed for system ${systemId}: ${err?.message ?? String(err)}`
        );
      }
    }

    // 3) Refresh tables once at the end
    await fetchSystems();
    await fetchAutodiscovery();

    if (uploadFailures.length > 0) {
      // Throw a single summarized error so the caller can show a nice status.
      const summary =
        uploadFailures.length === 1
          ? uploadFailures[0]
          : `${uploadFailures.length} CSV uploads failed. ${uploadFailures.join(
              "; "
            )}`;
      throw new Error(summary);
    }
  };

  /** Handle file selection for a single autodiscovery row. */
  const onSelectAutoCsv = (systemId: number, file: File | null) => {
    setAutoCsvMap((prev) => ({ ...prev, [systemId]: file }));
  };

  /** -------------------- Render ---------------------------------------- */

  return (
    <>
      <h2 className="section-title">Manage Monitoring Portfolio</h2>
      <div className="gold-rule" aria-hidden="true" />

      <AutodiscoverySection
        autoItems={autoItems}
        autoLoading={autoLoading}
        autoError={autoError}
        portfolioIdSet={portfolioIdSet}
        autoCsvMap={autoCsvMap}
        onRunAutodiscovery={fetchAutodiscovery}
        onAddAutodiscovered={onAddAutodiscovered}
        onSelectAutoCsv={onSelectAutoCsv}
        onBulkAddSelected={onBulkAddSelected}
      />

      <PortfolioSection
        systems={systems}
        systemsLoading={systemsLoading}
        systemsError={systemsError}
        purgeOnDelete={purgeOnDelete}
        purgeOnUnset={purgeOnUnset}
        setPurgeOnDelete={setPurgeOnDelete}
        setPurgeOnUnset={setPurgeOnUnset}
        showAdd={showAdd}
        setShowAdd={setShowAdd}
        newSystemId={newSystemId}
        setNewSystemId={setNewSystemId}
        csvFile={csvFile}
        setCsvFile={setCsvFile}
        submitting={submitting}
        submitError={submitError}
        onAddSystem={onAddSystem}
        onDeleteSystem={onDeleteSystem}
        onUnsetCsv={onUnsetCsv}
        fetchSystems={fetchSystems}
        fileInputRef={fileInputRef}
      />
    </>
  );
}

