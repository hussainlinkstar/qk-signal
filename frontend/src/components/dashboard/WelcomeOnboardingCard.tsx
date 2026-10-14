import React from "react";
import Link from "next/link";
import { Sparkles, Activity, ArrowRight, ShieldCheck } from "lucide-react";
import { motion } from "motion/react";
import { GlassCard } from "@/components/ui/GlassComponents";
import Button from "@/components/ui/Button";
import GeoIcon from "@/components/ui/GeoIcon";

type WelcomeOnboardingCardProps = {
  className?: string;
};

export default function WelcomeOnboardingCard({ className }: WelcomeOnboardingCardProps) {
  const containerVariants = {
    hidden: { opacity: 0 },
    show: {
      opacity: 1,
      transition: {
        staggerChildren: 0.1,
      },
    },
  };

  const itemVariants = {
    hidden: { opacity: 0, y: 10 },
    show: {
      opacity: 1,
      y: 0,
      transition: { type: "spring" as const, stiffness: 300, damping: 24 },
    },
  };

  return (
    <GlassCard
      className={`p-0 relative overflow-hidden group border-primary/20 bg-primary/[0.02] shadow-[0_0_50px_-15px_rgba(6,182,212,0.1)] ${className ?? ""}`}
    >
      {/* Background Decor */}
      <div className="absolute top-0 right-0 p-12 opacity-[0.03] pointer-events-none transition-opacity duration-700 group-hover:opacity-[0.08] grayscale mix-blend-overlay">
        <Sparkles className="h-48 w-48 text-primary" />
      </div>
      <div className="absolute -inset-24 bg-linear-to-br from-primary/10 via-transparent to-indigo-500/10 blur-3xl opacity-30 pointer-events-none group-hover:opacity-50 transition-opacity duration-1000" />

      <div className="p-8 md:p-12 relative z-10 flex flex-col md:flex-row gap-8 md:gap-16 items-start md:items-center">
        {/* Left Side: Messaging */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="show"
          className="flex-1 space-y-6"
        >
          <motion.div variants={itemVariants} className="flex flex-col items-start gap-4">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shadow-[0_0_30px_rgba(6,182,212,0.2)]">
                <ShieldCheck className="w-5 h-5" />
              </div>
              <div>
                <p className="text-[10px] font-black uppercase tracking-[0.3em] text-primary">
                  Intelligence Hub
                </p>
                <h2 className="text-2xl font-black text-(--t-1) uppercase tracking-tight mt-0.5">
                  Welcome to Qiko Signal
                </h2>
              </div>
            </div>

            <motion.p
              variants={itemVariants}
              className="text-sm text-(--t-2) leading-relaxed max-w-lg font-medium"
            >
              Your workspace is currently empty. Create your first project to unlock guided audits,
              AI visibility monitoring, and optimization insights.
            </motion.p>
          </motion.div>

          <motion.div variants={itemVariants}>
            <Link href="/dashboard/overview#new-project">
              <Button
                variant="primary"
                className="h-12 px-8 rounded-xl shadow-[0_0_30px_-5px_var(--primary)] font-black uppercase tracking-widest text-[11px] group/cta ring-1 ring-primary/50"
              >
                Create Your First Project{" "}
                <ArrowRight className="w-4 h-4 ml-2 inline transition-transform group-hover/cta:translate-x-1" />
              </Button>
            </Link>
          </motion.div>
        </motion.div>

        {/* Right Side: Feature Grid */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="show"
          className="flex-1 grid gap-4 w-full"
        >
          {/* Projects Card */}
          <motion.div
            variants={itemVariants}
            className="rounded border border-(--line) bg-(--line-2) p-5  transition-all hover:bg-(--line-2) hover:border-(--line) group/feat shadow-inner"
          >
            <div className="flex items-start gap-4">
              <div className="h-8 w-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center shrink-0">
                <GeoIcon className="w-4 h-4" />
              </div>
              <div>
                <p className="text-[10px] font-black uppercase tracking-[0.2em] text-emerald-400 mb-1">
                  Performance Tracking
                </p>
                <h3 className="text-sm font-bold text-(--t-1) mb-2 tracking-wide uppercase">
                  SEO + AIO
                </h3>
                <ul className="space-y-1.5 text-[11px] text-(--t-3) font-medium">
                  <li className="flex items-center gap-2 px-1">
                    <div className="h-1 w-1 bg-emerald-500/50 rounded-full" /> Track SEO & AIO
                    performance.
                  </li>
                  <li className="flex items-center gap-2 px-1">
                    <div className="h-1 w-1 bg-emerald-500/50 rounded-full" /> Monitor AI search
                    visibility changes.
                  </li>
                </ul>
              </div>
            </div>
          </motion.div>

          {/* Competitors Card */}
          <motion.div
            variants={itemVariants}
            className="rounded border border-(--line) bg-(--line-2) p-5  transition-all hover:bg-(--line-2) hover:border-(--line) group/feat shadow-inner"
          >
            <div className="flex items-start gap-4">
              <div className="h-8 w-8 rounded-lg bg-[color-mix(in_srgb,var(--purple)_10%,transparent)] border border-[color-mix(in_srgb,var(--purple)_20%,transparent)] text-(--purple) flex items-center justify-center shrink-0">
                <Activity className="w-4 h-4" />
              </div>
              <div>
                <p className="text-[10px] font-black uppercase tracking-[0.2em] text-(--purple) mb-1">
                  Optimization Guidance
                </p>
                <h3 className="text-sm font-bold text-(--t-1) mb-2 tracking-wide uppercase">
                  Actionable Roadmaps
                </h3>
                <ul className="space-y-1.5 text-[11px] text-(--t-3) font-medium">
                  <li className="flex items-center gap-2 px-1">
                    <div className="h-1 w-1 bg-[color-mix(in_srgb,var(--purple)_50%,transparent)] rounded-full" />{" "}
                    Get actionable optimization recommendations.
                  </li>
                  <li className="flex items-center gap-2 px-1">
                    <div className="h-1 w-1 bg-[color-mix(in_srgb,var(--purple)_50%,transparent)] rounded-full" />{" "}
                    Prioritize what to fix first.
                  </li>
                </ul>
              </div>
            </div>
          </motion.div>
        </motion.div>
      </div>
    </GlassCard>
  );
}
