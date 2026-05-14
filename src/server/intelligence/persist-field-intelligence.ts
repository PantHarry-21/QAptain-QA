import { prisma } from '@/lib/prisma';
import type { Prisma } from '@prisma/client';
import type { ClassifiedField } from '@/server/intelligence/field-classifier';
import { inferValidationRules } from '@/server/intelligence/validation-inferrer';

export async function upsertFieldIntelligence(
  workspaceId: string,
  routeFingerprint: string,
  cf: ClassifiedField,
): Promise<void> {
  const fd = await prisma.fieldDefinition.upsert({
    where: {
      workspaceId_routeFingerprint_fieldKey: {
        workspaceId,
        routeFingerprint,
        fieldKey: cf.fieldKey,
      },
    },
    create: {
      workspaceId,
      routeFingerprint,
      fieldKey: cf.fieldKey,
      label: cf.labelText || cf.placeholder || cf.fieldKey,
      fieldType: cf.type,
      semanticClass: cf.semanticClass,
      semanticMeaning: cf.semanticMeaning,
      required: cf.required,
      minLength: cf.minLength ?? undefined,
      maxLength: cf.maxLength ?? undefined,
      pattern: cf.pattern || undefined,
      inputMode: cf.inputMode || undefined,
      ariaLabel: cf.ariaLabel || undefined,
      placeholderText: cf.placeholder || undefined,
      optionsJson: cf.options?.length ? cf.options : undefined,
      testPriority: cf.testPriority,
      metadata: {
        tag: cf.tag,
        name: cf.name,
        id: cf.id,
      },
    },
    update: {
      label: cf.labelText || cf.placeholder || cf.fieldKey,
      fieldType: cf.type,
      semanticClass: cf.semanticClass,
      semanticMeaning: cf.semanticMeaning,
      required: cf.required,
      minLength: cf.minLength ?? undefined,
      maxLength: cf.maxLength ?? undefined,
      pattern: cf.pattern || undefined,
      inputMode: cf.inputMode || undefined,
      ariaLabel: cf.ariaLabel || undefined,
      placeholderText: cf.placeholder || undefined,
      optionsJson: cf.options?.length ? cf.options : undefined,
      testPriority: cf.testPriority,
      metadata: {
        tag: cf.tag,
        name: cf.name,
        id: cf.id,
      },
    },
  });

  await prisma.validationRule.deleteMany({
    where: { fieldDefinitionId: fd.id },
  });

  const rules = inferValidationRules(cf);
  if (rules.length > 0) {
    await prisma.validationRule.createMany({
      data: rules.map((r) => ({
        workspaceId,
        fieldDefinitionId: fd.id,
        routeFingerprint,
        fieldKey: cf.fieldKey,
        ruleType: r.ruleType,
        source: r.source,
        details: r.details as Prisma.InputJsonValue,
      })),
    });
  }
}

export async function findFieldDefinitionForHint(
  workspaceId: string,
  _routeFingerprint: string,
  fieldHint: string,
): Promise<{ semanticClass: string; testPriority: number; fieldKey: string } | null> {
  const hint = fieldHint.toLowerCase().trim();
  const rows = await prisma.fieldDefinition.findMany({
    where: { workspaceId },
    orderBy: { testPriority: 'desc' },
    take: 500,
  });
  let best: (typeof rows)[0] | null = null;
  let bestScore = 0;
  for (const r of rows) {
    const blob = `${r.fieldKey} ${r.label || ''} ${r.semanticMeaning || ''}`.toLowerCase();
    let score = 0;
    if (blob.includes(hint) || hint.includes(r.fieldKey.toLowerCase())) score += 10;
    if ((r.label || '').toLowerCase().includes(hint)) score += 8;
    if (score > bestScore) {
      bestScore = score;
      best = r;
    }
  }
  if (!best || bestScore === 0) return null;
  return {
    semanticClass: best.semanticClass || best.fieldType,
    testPriority: best.testPriority,
    fieldKey: best.fieldKey,
  };
}
