"""Radar (social listening): what people say about the workspace's brand and its competitors, outside its own
accounts too, explained as events with a suggested next step.

Pipeline: ``collectors`` (sources) → ``service.collect`` (match the query, store ``Mention`` rows) →
``analysis`` (sentiment, intent, topic, emotion; AI with a lexicon fallback) → ``detection`` (spikes, crises,
sales opportunities, competitor moves, influencers, rising words → ``RadarEvent`` with a written card) →
actions in the rest of the platform (inbox, studio, planner, approvals, notifications, reports).

Plan: feature ``listening`` (Pro and up), resource ``listening_queries``; the X source is the feature
``listening_x`` (Business and up) with a monthly cap per workspace.
"""
