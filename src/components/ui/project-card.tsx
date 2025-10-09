'use client';

import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { motion } from "framer-motion";

const CircleProgress = ({ percentage, color }: { percentage: number; color: string }) => {
  const radius = 50;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (percentage / 100) * circumference;

  return (
    <svg width="120" height="120" viewBox="0 0 120 120" className="transform -rotate-90">
      <circle
        className="text-border"
        strokeWidth="10"
        stroke="currentColor"
        fill="transparent"
        r={radius}
        cx="60"
        cy="60"
      />
      <motion.circle
        className={`text-${color}`}
        strokeWidth="10"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        stroke="currentColor"
        fill="transparent"
        r={radius}
        cx="60"
        cy="60"
        initial={{ strokeDashoffset: circumference }}
        animate={{ strokeDashoffset: offset }}
        transition={{ duration: 1.5, ease: "easeOut" }}
      />
      <text
        x="50%"
        y="50%"
        textAnchor="middle"
        dy=".3em"
        className="text-2xl font-bold fill-foreground transform rotate-90 origin-center"
      >
        {`${percentage}%`}
      </text>
    </svg>
  );
};

export const ProjectCard = ({ project }: { project: any }) => {
  return (
    <Card className="hover:border-accent transition-colors duration-300">
      <CardHeader>
        <CardTitle>{project.name}</CardTitle>
        <CardDescription>{project.description}</CardDescription>
      </CardHeader>
      <CardContent className="flex justify-around items-center">
        <div className="flex flex-col items-center">
          <CircleProgress percentage={project.coverage} color="accent" />
          <span className="mt-2 text-sm text-muted-foreground">Coverage</span>
        </div>
        <div className="flex flex-col items-center">
          <CircleProgress percentage={project.passRate} color="[#34D399]" />
          <span className="mt-2 text-sm text-muted-foreground">Pass Rate</span>
        </div>
        <div className="flex flex-col items-center">
          <CircleProgress percentage={project.risk} color="[#F87171]" />
          <span className="mt-2 text-sm text-muted-foreground">Risk</span>
        </div>
      </CardContent>
    </Card>
  );
};
