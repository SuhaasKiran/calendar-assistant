import { useMemo, useState } from "react";

type InterruptValue = {
  kind?: string;
  summary?: string;
  question?: string;
  unit?: string;
  proposals?: unknown;
  actions?: Array<{ id?: string; label?: string }>;
};

type Props = {
  interrupts: Array<{ id: string; value: unknown }>;
  onResume: (value: unknown) => void | Promise<void>;
  disabled?: boolean;
};

function asValue(v: unknown): InterruptValue | null {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return v as InterruptValue;
  }
  return null;
}

/**
 * Human-in-the-loop: backend pauses the graph with an interrupt payload.
 * Approval shows a plain-text summary; clarification shows the question (not JSON).
 */
export default function InterruptPanel({
  interrupts,
  onResume,
  disabled,
}: Props) {
  const [showEditForm, setShowEditForm] = useState(false);
  const [editText, setEditText] = useState("");
  const first = interrupts[0];
  const val = first ? asValue(first.value) : null;
  const kind = val?.kind;
  const actionIds = useMemo(
    () =>
      new Set(
        (val?.actions ?? [])
          .map((a) => String(a.id ?? "").trim().toLowerCase())
          .filter(Boolean),
      ),
    [val?.actions],
  );
  const hasExplicitActions = actionIds.size > 0;
  const canApprove = !hasExplicitActions || actionIds.has("approve");
  const canEdit = !hasExplicitActions || actionIds.has("edit");
  const canReject = !hasExplicitActions || actionIds.has("reject");

  async function submitEdit() {
    const feedback = editText.trim();
    if (!feedback || disabled) return;
    await onResume({ action: "edit", feedback });
    setShowEditForm(false);
    setEditText("");
  }

  return (
    <div className="interrupt-panel" role="region" aria-label="Assistant needs confirmation">
      {kind === "clarification" ? (
        <>
          <p className="interrupt-title">Clarification</p>
          <pre className="interrupt-body">{val?.question ?? JSON.stringify(first?.value)}</pre>
        </>
      ) : kind === "approval" ? (
        <>
          <p className="interrupt-title">Confirmation required</p>
          <pre className="interrupt-body">{val?.summary ?? "(no summary)"}</pre>
        </>
      ) : (
        <>
          <p className="interrupt-title">Action required</p>
          <pre className="interrupt-body">{JSON.stringify(interrupts, null, 2)}</pre>
        </>
      )}
      <div className="interrupt-actions">
        {canApprove && (
          <button
            type="button"
            className="btn primary"
            disabled={disabled}
            onClick={() => void onResume({ action: "approve" })}
          >
            Approve
          </button>
        )}
        {canEdit && !showEditForm && (
          <button
            type="button"
            className="btn"
            disabled={disabled}
            onClick={() => setShowEditForm(true)}
          >
            Edit
          </button>
        )}
        {canReject && !showEditForm && (
          <button
            type="button"
            className="btn"
            disabled={disabled}
            onClick={() => void onResume({ action: "reject" })}
          >
            Reject
          </button>
        )}
      </div>
      {showEditForm && (
        <div className="interrupt-edit">
          <textarea
            className="chat-input"
            rows={3}
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            placeholder="Describe the changes you want..."
            disabled={disabled}
          />
          <div className="interrupt-actions">
            <button
              type="button"
              className="btn primary"
              disabled={disabled || !editText.trim()}
              onClick={() => void submitEdit()}
            >
              Submit edits
            </button>
            <button
              type="button"
              className="btn"
              disabled={disabled}
              onClick={() => {
                setShowEditForm(false);
                setEditText("");
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {canReject && showEditForm && (
        <div className="interrupt-actions">
          <button
            type="button"
            className="btn"
            disabled={disabled}
            onClick={() => void onResume({ action: "reject" })}
          >
            Reject
          </button>
        </div>
      )}
    </div>
  );
}
