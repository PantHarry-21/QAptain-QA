'use client';

import { cn } from "@/lib/utils";
import React from "react";
import { motion } from "framer-motion";

export const HeroBackground = ({ className }: { className?: string }) => {
  return (
    <div
      className={cn(
        "fixed inset-0 -z-10 h-full w-full overflow-hidden",
        className
      )}
    >
      {/* Main background color */}
      <div className="absolute inset-0 bg-background" />

      {/* Aurora Gradients */}
      <motion.div
        className="absolute inset-0 z-0"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 2 }}
      >
        <div
          className="absolute bottom-0 left-[-20%] right-0 top-[-10%] h-[500px] w-[500px] rounded-full bg-[radial-gradient(circle_farthest-side,rgba(120,81,255,0.15),rgba(255,255,255,0))]"
        />
        <div
          className="absolute bottom-0 right-[-20%] top-[-10%] h-[500px] w-[500px] rounded-full bg-[radial-gradient(circle_farthest-side,rgba(120,81,255,0.15),rgba(255,255,255,0))]"
        />
      </motion.div>

      {/* Animated Grid */}
      <motion.div
        className="absolute inset-0 z-10"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 1, delay: 0.5 }}
      >
        <div
          className="absolute inset-0 bg-[linear-gradient(to_right,#ffffff0d_1px,transparent_1px),linear-gradient(to_bottom,#ffffff0d_1px,transparent_1px)] bg-[size:36px_36px] [mask-image:radial-gradient(ellipse_50%_50%_at_50%_50%,#000_70%,transparent_100%)]"
        />
      </motion.div>
    </div>
  );
};
