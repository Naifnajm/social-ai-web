import type { ReactNode } from "react";
import { Icon } from "@/components/icon";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-[420px]">
        <div className="mb-6 flex items-center justify-center gap-2.5">
          <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-ink text-white shadow-[0_10px_24px_-10px_rgba(0,0,0,.6)]">
            <Icon name="auto_awesome" size={22} duo />
          </span>
          <span className="text-xl font-bold tracking-tight">Stravica Social</span>
        </div>
        <div className="glass-strong rounded-[24px] p-6 sm:p-7">{children}</div>
      </div>
    </div>
  );
}
