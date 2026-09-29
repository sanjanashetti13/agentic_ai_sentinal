import { cn } from "@/lib/utils";
import {
  createContext,
  useContext,
  useState,
  type ComponentProps,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { AnimatePresence, motion, type HTMLMotionProps } from "framer-motion";
import { Menu, X } from "lucide-react";

export type SidebarNavLink = {
  label: string;
  href?: string;
  icon: ReactNode;
  onClick?: () => void;
  active?: boolean;
  badge?: number;
  indent?: boolean;
  heading?: boolean;
};

type SidebarContextProps = {
  open: boolean;
  setOpen: Dispatch<SetStateAction<boolean>>;
  animate: boolean;
};

const SidebarContext = createContext<SidebarContextProps | undefined>(
  undefined,
);

export const useSidebar = () => {
  const context = useContext(SidebarContext);
  if (!context) {
    throw new Error("useSidebar must be used within a SidebarProvider");
  }
  return context;
};

export const SidebarProvider = ({
  children,
  open: openProp,
  setOpen: setOpenProp,
  animate = true,
}: {
  children: ReactNode;
  open?: boolean;
  setOpen?: Dispatch<SetStateAction<boolean>>;
  animate?: boolean;
}) => {
  const [openState, setOpenState] = useState(false);
  const open = openProp !== undefined ? openProp : openState;
  const setOpen = setOpenProp !== undefined ? setOpenProp : setOpenState;

  return (
    <SidebarContext.Provider value={{ open, setOpen, animate }}>
      {children}
    </SidebarContext.Provider>
  );
};

export const Sidebar = ({
  children,
  open,
  setOpen,
  animate,
}: {
  children: ReactNode;
  open?: boolean;
  setOpen?: Dispatch<SetStateAction<boolean>>;
  animate?: boolean;
}) => {
  return (
    <SidebarProvider open={open} setOpen={setOpen} animate={animate}>
      {children}
    </SidebarProvider>
  );
};

export const SidebarBody = (props: HTMLMotionProps<"div">) => {
  return (
    <>
      <DesktopSidebar {...props} />
      <MobileSidebar {...(props as ComponentProps<"div">)} />
    </>
  );
};

export const DesktopSidebar = ({
  className,
  children,
  ...props
}: HTMLMotionProps<"div">) => {
  const { open, setOpen, animate } = useSidebar();
  return (
    <motion.div
      className={cn(
        "sentinel-sidebar hidden h-full w-[260px] shrink-0 flex-col px-3 py-4 md:flex",
        className,
      )}
      animate={{
        width: animate ? (open ? "260px" : "76px") : "260px",
      }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      {...props}
    >
      {children}
    </motion.div>
  );
};

export const MobileSidebar = ({
  className,
  children,
  ...props
}: ComponentProps<"div">) => {
  const { open, setOpen } = useSidebar();
  return (
    <>
      <div
        className={cn(
          "sentinel-sidebar-mobile flex h-10 w-full flex-row items-center justify-between px-4 py-4 md:hidden",
        )}
        {...props}
      >
        <div className="z-20 flex w-full justify-end">
            <Menu
            className="cursor-pointer text-[color:var(--ivory)]"
            onClick={() => setOpen(!open)}
          />
        </div>
        <AnimatePresence>
          {open && (
            <motion.div
              initial={{ x: "-100%", opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: "-100%", opacity: 0 }}
              transition={{
                duration: 0.3,
                ease: "easeInOut",
              }}
              className={cn(
                "sentinel-sidebar-drawer fixed inset-0 z-[100] flex h-full w-full flex-col justify-between p-10",
                className,
              )}
            >
              <div
                className="absolute right-10 top-10 z-50 cursor-pointer text-[color:var(--ivory)]"
                onClick={() => setOpen(!open)}
              >
                <X />
              </div>
              {children}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </>
  );
};

export const SidebarLink = ({
  link,
  className,
}: {
  link: SidebarNavLink;
  className?: string;
}) => {
  const { open, animate, setOpen } = useSidebar();

  function handleClick() {
    if (link.heading) {
      return;
    }
    link.onClick?.();
    setOpen(false);
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className={cn(
        "sidebar-link group/sidebar flex w-full items-center justify-start gap-2 text-left",
        link.active && "sidebar-link-active",
        link.indent && "pl-4",
        link.heading && "cursor-default opacity-70",
        className,
      )}
    >
      <span className="relative inline-flex shrink-0">
        {link.icon}
        {link.badge && link.badge > 0 ? (
          <span
            className="sidebar-badge absolute -right-1.5 -top-1.5 z-10 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[9px] font-semibold leading-none"
            aria-label={`${link.badge} pending alerts`}
          >
            {link.badge > 9 ? "9+" : link.badge}
          </span>
        ) : null}
      </span>
      <motion.span
        animate={{
          display: animate ? (open ? "inline-block" : "none") : "inline-block",
          opacity: animate ? (open ? 1 : 0) : 1,
        }}
        className="sidebar-link-label m-0 inline-block whitespace-pre p-0 text-sm transition duration-150 group-hover/sidebar:translate-x-1"
      >
        {link.label}
      </motion.span>
    </button>
  );
};
