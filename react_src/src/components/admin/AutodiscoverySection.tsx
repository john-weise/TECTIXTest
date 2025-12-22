// src/components/admin/AutodiscoverySection.tsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import type { AutodiscoveryItem } from "../../types/admin";
import FullscreenSpinnerOverlay from "./FullscreenSpinnerOverlay";

/** Join policy names for display (handles empty). */
const joinPolicies = (policies: string[] | null | undefined) =>
  policies && policies.length ? policies.join(", ") : "—";

/** Small inline SVG: plus icon (used for add buttons). */
const PlusIcon = ({ size = 18 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

/** Small inline SVG: checkmark (used to indicate true/has CSV / in portfolio). */
const CheckIcon = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path
      d="M5 13l4 4L19 7"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

/** Small inline SVG: "X" (used to indicate false/no CSV / not in portfolio). */
const XIcon = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

type AutodiscoverySectionProps = {
  autoItems: AutodiscoveryItem[];
  autoLoading: boolean;
  autoError: string;

  /** Optional external bulk status (can be omitted). */
  bulkAddLoading?: boolean;
  bulkAddStatus?: string;

  /** Systems already in the portfolio (for "in portfolio" checks). */
  portfolioIdSet: Set<number>;

  /** Per-row CSV selection map (keyed by system_id). */
  autoCsvMap: Record<number, File | null>;
  onSelectAutoCsv: (systemId: number, file: File | null) => void;

  /** Actions wired from parent. */
  onRunAutodiscovery: () => void | Promise<void>;
  onAddAutodiscovered: (systemId: number) => void | Promise<void>;

  /**
   * Bulk add hook.
   * Parent uses the /api/admin/systems batch style:
   *   POST { items: [{ system_id, csv_path: null }, ...] }
   * plus any per-system CSV uploads, then refreshes tables once.
   */
  onBulkAddSelected: (systemIds: number[]) => Promise<void>;
};

const AutodiscoverySection: React.FC<AutodiscoverySectionProps> = ({
  autoItems,
  autoLoading,
  autoError,
  bulkAddLoading,
  bulkAddStatus,
  portfolioIdSet,
  autoCsvMap: _autoCsvMap, // currently unused here; parent owns it + uses onSelectAutoCsv
  onSelectAutoCsv,
  onRunAutodiscovery,
  onAddAutodiscovered,
  onBulkAddSelected,
}) => {
  /** ---- Internal selection + bulk state -------------------------------- */

  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [localBulkLoading, setLocalBulkLoading] = useState<boolean>(false);
  const [localBulkStatus, setLocalBulkStatus] = useState<string>("");

  // Snapshot of how many systems we are adding in the *current* bulk run.
  // This freezes once Add Selected is clicked and only resets when the bulk work finishes.
  const [bulkSelectionCount, setBulkSelectionCount] = useState<number | null>(null);

  // Use external bulk state if provided, otherwise fall back to local.
  const effectiveBulkLoading = bulkAddLoading ?? localBulkLoading;
  const effectiveBulkStatus = bulkAddStatus ?? localBulkStatus;

  /** ---- Derived selection state ---------------------------------------- */

  // IDs of all autodiscovered systems that are NOT yet in the portfolio
  const missingIds = useMemo(
    () =>
      autoItems
        .filter((item) => !portfolioIdSet.has(item.system_id))
        .map((item) => item.system_id),
    [autoItems, portfolioIdSet]
  );

  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedCount = selectedIds.length;

  const allMissingSelected =
    missingIds.length > 0 && missingIds.every((id) => selectedIdSet.has(id));

  const someMissingSelected =
    missingIds.some((id) => selectedIdSet.has(id)) && !allMissingSelected;

  const headerCheckboxRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (headerCheckboxRef.current) {
      headerCheckboxRef.current.indeterminate = someMissingSelected;
    }
  }, [someMissingSelected]);

  const canRunSelectionActions =
    !autoLoading && !effectiveBulkLoading && autoItems.length > 0;

  const canAddSelected = canRunSelectionActions && selectedCount > 0;

  /** ---- Handlers ------------------------------------------------------- */

  const toggleRowSelection = (systemId: number, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(systemId);
      else next.delete(systemId);
      return Array.from(next);
    });
  };

  const toggleHeaderSelection = (checked: boolean) => {
    if (!checked) {
      // Unselect all missing
      setSelectedIds((prev) => prev.filter((id) => !missingIds.includes(id)));
    } else {
      // Select all missing
      setSelectedIds((prev) => {
        const next = new Set(prev);
        missingIds.forEach((id) => next.add(id));
        return Array.from(next);
      });
    }
  };

  const selectAllNotInPortfolio = () => {
    if (!canRunSelectionActions || missingIds.length === 0) return;
    setSelectedIds(missingIds);
  };

  const handleAddSelected = async () => {
    if (!selectedCount) return;

    // Snapshot the IDs we’re going to process so UI counts don’t jitter mid-run.
    const idsToProcess = [...selectedIds];
    const totalToAdd = idsToProcess.length;

    setBulkSelectionCount(totalToAdd);
    setLocalBulkStatus("");
    setLocalBulkLoading(true);

    try {
      // Let the parent do the efficient batch call using the new endpoint style.
      await onBulkAddSelected(idsToProcess);

      setLocalBulkStatus(
        `Successfully added ${totalToAdd} system${totalToAdd === 1 ? "" : "s"} to the portfolio.`
      );
    } catch (err: any) {
      // Debug output to browser console
      console.error(
        "[AutodiscoverySection] Bulk add failed",
        {
          error: err,
          message: err?.message,
          selectedIds: idsToProcess,
        }
      );

      const message = err?.message ?? String(err);
      setLocalBulkStatus(
        `Bulk add failed.${message ? ` Details: ${message}` : ""}`
      );
    } finally {
      setLocalBulkLoading(false);
      setSelectedIds([]);        // clear selection now that we're done
      setBulkSelectionCount(null); // release the frozen count — "systems to add" is now 0
    }
  };

  /** ---- Render --------------------------------------------------------- */

  const overlaySubtitle =
    bulkSelectionCount && bulkSelectionCount > 0
      ? `Adding ${bulkSelectionCount} system${bulkSelectionCount === 1 ? "" : "s"} to your monitoring portfolio.`
      : "Adding selected systems to your monitoring portfolio.";

  return (
    <>
      {/* Full-screen overlay while bulk add is running */}
      <FullscreenSpinnerOverlay
        visible={effectiveBulkLoading}
        title="Working…"
        subtitle={overlaySubtitle}
      />

      <div className="card" style={{ marginBottom: 16 }}>
        {/* Header / actions */}
        <div
          className="row"
          style={{ justifyContent: "space-between", alignItems: "center" }}
        >
          <div>
            <h3 className="admin-subhead" style={{ margin: 0 }}>
              Autodiscovery
            </h3>
            <div className="hint" style={{ marginTop: 4, fontSize: 12 }}>
              {autoItems.length > 0 ? (
                <>
                  {autoItems.length} system
                  {autoItems.length !== 1 ? "s" : ""} found • Selected: {selectedCount}
                </>
              ) : (
                <>Run Autodiscovery to list systems from eMASS fixtures.</>
              )}
            </div>
          </div>

          <div
            className="actions"
            style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}
          >
            <button
              className="secondary-button"
              onClick={() => onRunAutodiscovery()}
              disabled={autoLoading || effectiveBulkLoading}
              title="Scan fixtures for systems"
            >
              {autoLoading ? "Scanning…" : "Run Autodiscovery"}
            </button>

            <button
              className="generate-button"
              onClick={handleAddSelected}
              disabled={!canAddSelected}
              title={
                selectedCount === 0
                  ? "Select one or more systems to add"
                  : `Add selected system(s) to the portfolio`
              }
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                position: "relative",
              }}
            >
              {/* Constant label – no width jitter */}
              <PlusIcon />
              <span>Add Selected</span>
            </button>

            <button
              type="button"
              className="link-button"
              onClick={selectAllNotInPortfolio}
              disabled={!canRunSelectionActions || missingIds.length === 0}
              title="Select all autodiscovered systems that are not yet in the portfolio"
              style={{
                fontSize: 12,
                padding: 0,
                textDecoration: "underline",
                background: "none",
                border: "none",
                cursor:
                  !canRunSelectionActions || missingIds.length === 0 ? "default" : "pointer",
                opacity:
                  !canRunSelectionActions || missingIds.length === 0 ? 0.5 : 0.9,
              }}
            >
              Select all not in portfolio
            </button>
          </div>
        </div>

        {autoError && (
          <div className="error-banner" style={{ marginTop: 8 }}>
            {autoError}
          </div>
        )}
        {effectiveBulkStatus && !autoError && (
          <div className="hint" style={{ marginTop: 8 }}>
            {effectiveBulkStatus}
          </div>
        )}

        {/* Table */}
        <div
          className="table-scroll"
          role="region"
          aria-label="Autodiscovered Systems"
          style={{
            maxHeight: 360,
            overflow: "auto",
            border: "1px solid var(--border-color, #2a2a2a)",
            borderRadius: 8,
            marginTop: 12,
          }}
        >
          <table className="admin-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {/* Selection column */}
                <th
                  style={{
                    width: 40,
                    textAlign: "center",
                    padding: "10px 12px",
                    position: "sticky",
                    top: 0,
                    background: "var(--panel, #0b0c0e)",
                  }}
                >
                  <input
                    ref={headerCheckboxRef}
                    type="checkbox"
                    disabled={
                      !canRunSelectionActions ||
                      missingIds.length === 0 ||
                      autoItems.length === 0
                    }
                    checked={allMissingSelected}
                    onChange={(e) => toggleHeaderSelection(e.target.checked)}
                    aria-label="Select all not-in-portfolio systems on this list"
                  />
                </th>

                <th
                  style={{
                    textAlign: "left",
                    padding: "10px 12px",
                    position: "sticky",
                    top: 0,
                    background: "var(--panel, #0b0c0e)",
                  }}
                >
                  System ID
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "10px 12px",
                    position: "sticky",
                    top: 0,
                    background: "var(--panel, #0b0c0e)",
                  }}
                >
                  In Portfolio
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "10px 12px",
                    position: "sticky",
                    top: 0,
                    background: "var(--panel, #0b0c0e)",
                  }}
                >
                  Enrolled Policies
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "10px 12px",
                    position: "sticky",
                    top: 0,
                    background: "var(--panel, #0b0c0e)",
                  }}
                >
                  Optional CSV
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "10px 12px",
                    position: "sticky",
                    top: 0,
                    background: "var(--panel, #0b0c0e)",
                  }}
                >
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {(!autoItems || autoItems.length === 0) && !autoLoading && (
                <tr>
                  <td colSpan={6} style={{ padding: 16, textAlign: "center", color: "#aaa" }}>
                    No autodiscovered systems. Click <em>Run Autodiscovery</em> to scan fixtures.
                  </td>
                </tr>
              )}
              {autoItems.map((item) => {
                const inPortfolio = portfolioIdSet.has(item.system_id);
                const selectable = !inPortfolio;
                const isSelected = selectable && selectedIdSet.has(item.system_id);

                return (
                  <tr key={item.system_id} className="admin-row">
                    {/* Row checkbox */}
                    <td
                      style={{
                        padding: "10px 12px",
                        textAlign: "center",
                        verticalAlign: "middle",
                      }}
                    >
                      <input
                        type="checkbox"
                        disabled={!selectable || autoLoading || effectiveBulkLoading}
                        checked={!!isSelected}
                        onChange={(e) =>
                          toggleRowSelection(item.system_id, e.target.checked)
                        }
                        aria-label={`Select system ${item.system_id}`}
                      />
                    </td>

                    <td style={{ padding: "10px 12px" }}>
                      <code>{item.system_id}</code>
                    </td>

                    <td style={{ padding: "10px 12px" }}>
                      {inPortfolio ? (
                        <span className="badge badge-ok" title="Already in portfolio">
                          <CheckIcon /> <span style={{ marginLeft: 6 }}>yes</span>
                        </span>
                      ) : (
                        <span className="badge badge-warn" title="Not yet in portfolio">
                          <XIcon /> <span style={{ marginLeft: 6 }}>no</span>
                        </span>
                      )}
                    </td>

                    <td
                      style={{ padding: "10px 12px" }}
                      title={joinPolicies(item.policies)}
                    >
                      {joinPolicies(item.policies)}
                    </td>

                    <td style={{ padding: "10px 12px", minWidth: 260 }}>
                      <input
                        type="file"
                        accept=".csv,text/csv"
                        className="admin-input"
                        onChange={(e) =>
                          onSelectAutoCsv(item.system_id, e.target.files?.[0] || null)
                        }
                        disabled={inPortfolio || effectiveBulkLoading}
                        title={
                          inPortfolio
                            ? "Already in portfolio"
                            : "Optional CSV to associate on add"
                        }
                      />
                    </td>

                    <td style={{ padding: "10px 12px" }}>
                      <button
                        className="generate-button"
                        onClick={() => onAddAutodiscovered(item.system_id)}
                        disabled={inPortfolio || effectiveBulkLoading}
                        title={inPortfolio ? "Already added" : "Add to portfolio"}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 6,
                        }}
                      >
                        <PlusIcon /> Add
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="hint" style={{ marginTop: 8 }}>
          Autodiscovery scans eMASS for systems within your organization and shows policy enrollment
          (if any). Use the checkboxes to select systems that are not yet in the portfolio, then{" "}
          <em>Add Selected</em> to bulk-enroll them. CSVs can be attached now per-row or later from
          the Systems table.
        </div>
      </div>
    </>
  );
};

export default AutodiscoverySection;


