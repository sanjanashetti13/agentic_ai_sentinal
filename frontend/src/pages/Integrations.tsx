import type { GmailStatusResponse } from "../api/gmail";
import { GmailIntegrations } from "../components/GmailIntegrations";

type IntegrationsPageProps = {
  gmailStatus: GmailStatusResponse | null;
  onRefreshGmail: () => Promise<void>;
};

export function IntegrationsPage({
  gmailStatus,
  onRefreshGmail,
}: IntegrationsPageProps) {
  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Integrations</h2>
          <p className="muted">
            Gmail → Pub/Sub → Monitoring Agent → Analysis Agent → Action Agent.
            Incoming mail is evaluated against your goals; only relevant messages
            create alerts.
          </p>
        </div>
      </div>
      <GmailIntegrations status={gmailStatus} onRefresh={onRefreshGmail} />
    </section>
  );
}
