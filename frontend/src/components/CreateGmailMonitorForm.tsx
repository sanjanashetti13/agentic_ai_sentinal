import { useState } from "react";
import { createMonitor } from "../api/monitors";
import type { Monitor } from "../types";

const SUGGESTIONS = [
  "Tell me when I receive important emails about internship applications, interviews, or job offers.",
  "Tell me about scholarship application updates.",
  "Tell me about college deadlines.",
  "Tell me when I receive interview invitations.",
  "Tell me about important project emails.",
];

type CreateGmailMonitorFormProps = {
  onCreated: (monitor: Monitor) => void;
  onCancel: () => void;
};

export function CreateGmailMonitorForm({
  onCreated,
  onCancel,
}: CreateGmailMonitorFormProps) {
  const [goal, setGoal] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit() {
    if (!goal.trim()) {
      setError("Describe what Sentinel should watch for.");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      const created = await createMonitor({
        goal: goal.trim(),
        kind: "gmail",
      });
      onCreated(created);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not create the Gmail monitor.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onCancel}>
      <div
        className="form-card gmail-modal"
        role="dialog"
        aria-labelledby="gmail-create-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h3 id="gmail-create-title">Create Gmail Monitor</h3>
        <label htmlFor="gmail-goal">What should Sentinel watch for?</label>
        <textarea
          id="gmail-goal"
          rows={5}
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          placeholder="Tell me when I receive important emails about internship applications, interviews, or job offers."
          required
        />
        <p className="muted suggestion-label">Examples</p>
        <div className="suggestion-row">
          {SUGGESTIONS.map((item) => (
            <button
              key={item}
              className="suggestion-chip"
              type="button"
              onClick={() => {
                setGoal(item);
                setError(null);
              }}
            >
              {item.replace(/^Tell me (when I receive |about )?/i, "").replace(/\.$/, "")}
            </button>
          ))}
        </div>
        {error ? <p className="error">{error}</p> : null}
        <div className="actions">
          <button className="secondary" type="button" onClick={onCancel}>
            Cancel
          </button>
          <button
            className="primary"
            type="button"
            disabled={saving}
            onClick={() => void handleSubmit()}
          >
            {saving ? "Creating..." : "Create Monitor"}
          </button>
        </div>
      </div>
    </div>
  );
}
