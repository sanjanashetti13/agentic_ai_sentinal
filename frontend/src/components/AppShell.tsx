import { useState, type ReactNode } from "react";
import {
  Bell,
  Globe2,
  LayoutDashboard,
  Mail,
  Plug,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Sidebar,
  SidebarBody,
  SidebarLink,
} from "@/components/ui/sidebar";
import type { AppView } from "../utils/views";

const BACKGROUND_VIDEO =
  "/Animate_image_into_looping_backg\u2026_20260925120646.mp4";

type AppShellProps = {
  current: AppView;
  pendingAlerts: number;
  onNavigate: (view: AppView) => void;
  children: ReactNode;
};

export function AppShell({
  current,
  pendingAlerts,
  onNavigate,
  children,
}: AppShellProps) {
  const [open, setOpen] = useState(false);
  const links = [
    {
      label: "Dashboard",
      icon: <LayoutDashboard className="h-5 w-5 shrink-0" />,
      onClick: () => onNavigate("dashboard"),
      active: current === "dashboard",
    },
    {
      label: "Web Monitoring",
      icon: <Globe2 className="h-5 w-5 shrink-0" />,
      onClick: () => onNavigate("monitors"),
      active: current === "monitors",
    },
    {
      label: "Gmail",
      icon: <Mail className="h-5 w-5 shrink-0" />,
      onClick: () => onNavigate("gmail"),
      active: current === "gmail",
    },
    {
      label: "Alerts",
      icon: <Bell className="h-5 w-5 shrink-0" />,
      onClick: () => onNavigate("alerts"),
      active: current === "alerts",
      badge: pendingAlerts,
    },
    {
      label: "Integrations",
      icon: <Plug className="h-5 w-5 shrink-0" />,
      onClick: () => onNavigate("integrations"),
      active: current === "integrations",
    },
  ];

  return (
    <div
      className={cn(
        "app-shell flex h-screen w-full flex-1 flex-col overflow-hidden md:flex-row",
      )}
    >
      <video
        className="scene-video"
        autoPlay
        muted
        loop
        playsInline
        poster="/landscape.jpg"
        aria-hidden="true"
      >
        <source src={encodeURI(BACKGROUND_VIDEO)} type="video/mp4" />
      </video>
      <div className="scene-shade" aria-hidden="true" />
      <Sidebar open={open} setOpen={setOpen}>
        <SidebarBody className="justify-between gap-10">
          <div className="flex flex-1 flex-col overflow-x-hidden overflow-y-auto">
            {open ? <Logo /> : <LogoIcon />}
            <nav className="mt-8 flex flex-col gap-2" aria-label="Primary">
              {links.map((link) => (
                <SidebarLink key={link.label} link={link} />
              ))}
            </nav>
          </div>
        </SidebarBody>
      </Sidebar>
      <div className="app-main flex min-w-0 flex-1 overflow-x-hidden">
        <img
          className="scene-wordmark"
          src="/logo-mark.png?v=5"
          alt=""
          aria-hidden="true"
        />
        <div className="app-main-scroll">
          <div className="page-brand">
            <img
              src="/logo-mark.png?v=5"
              alt="SENTINEL — Always watching what matters"
            />
          </div>
          <div className="app-main-inner">{children}</div>
        </div>
      </div>
    </div>
  );
}

function Logo() {
  return (
    <div className="relative z-20 flex items-center justify-center py-2">
      <img
        src="/logo-mark.png?v=5"
        alt="SENTINEL — Always watching what matters"
        className="h-auto w-full max-w-[220px] object-contain"
      />
    </div>
  );
}

function LogoIcon() {
  return (
    <div className="relative z-20 flex items-center justify-center py-1">
      <img
        src="/logo-mark.png?v=5"
        alt="SENTINEL"
        className="h-11 w-11 object-cover object-center"
      />
    </div>
  );
}
