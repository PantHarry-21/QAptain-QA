'use client';

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Bot, X, Sparkles, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils.client";

export function AssistantPanel() {
  const [isOpen, setIsOpen] = useState(true);

  if (!isOpen) {
    return (
      <div className="fixed bottom-6 right-6 z-50">
        <Button onClick={() => setIsOpen(true)} size="icon" className="rounded-full h-14 w-14 bg-accent hover:bg-accent/90 shadow-lg shadow-accent/20">
          <Bot className="h-7 w-7" />
        </Button>
      </div>
    );
  }

  return (
    <AnimatePresence>
      <motion.div 
        className="fixed top-0 right-0 h-full w-[350px] z-40"
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      >
        <div className="relative h-full w-full bg-card/60 backdrop-blur-md border-l border-border p-4 flex flex-col">
          {/* Glow effect */}
          <div className="absolute -left-40 top-1/4 w-80 h-80 bg-accent/10 rounded-full blur-3xl -z-10" />

          {/* Header */}
          <div className="flex items-center justify-between pb-4 border-b border-border/50">
            <div className="flex items-center gap-2">
              <Sparkles className="w-6 h-6 text-accent" />
              <h2 className="text-lg font-bold">QAptain AI</h2>
            </div>
            <Button variant="ghost" size="icon" onClick={() => setIsOpen(false)}>
              <X className="h-5 w-5" />
            </Button>
          </div>

          {/* Chat Area (Placeholder) */}
          <div className="flex-1 py-4 space-y-4 overflow-y-auto">
            <div className="flex gap-2">
              <div className="w-8 h-8 rounded-full bg-accent flex items-center justify-center shrink-0"><Bot className="w-5 h-5 text-accent-foreground"/></div>
              <div className="p-3 rounded-lg bg-background/50">
                <p className="text-sm">Hello! How can I help you automate your QA process today?</p>
              </div>
            </div>
          </div>

          {/* Action Shortcuts & Input */}
          <div className="pt-4 border-t border-border/50 space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <Button variant="outline" size="sm" className="text-xs">Generate Test Cases</Button>
              <Button variant="outline" size="sm" className="text-xs">Summarize Runs</Button>
              <Button variant="outline" size="sm" className="text-xs">Assign Tasks</Button>
              <Button variant="outline" size="sm" className="text-xs">Analyze Risk</Button>
            </div>
            <div className="flex items-center gap-2">
              <Input placeholder="Ask QAptain AI..." className="bg-background/50" />
              <Button size="icon" className="bg-accent hover:bg-accent/90"><Send className="h-4 w-4"/></Button>
            </div>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
