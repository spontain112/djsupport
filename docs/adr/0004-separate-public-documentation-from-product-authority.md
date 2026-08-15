# Separate public documentation from product authority

DJ Support will publish its Mintlify site from the separate
`spontain112/djsupport-docs` repository. That repository owns audience-focused
explanation, navigation, and visual presentation; this repository remains the
only authority for product behavior, domain language, commands, stable release
state, schemas, and architecture decisions. This boundary lets the public site
translate DJ Support for nontechnical working DJs without reshaping canonical
product documentation around a marketing or onboarding surface.

The site has two native, independently navigable sections. **Use DJ Support**
is the default and guides a macOS DJ through a local Agent Client toward a
read-only Preview of one selected Rekordbox playlist. **Build DJ Support** holds
contributor setup and technical reference. Both sections consume the same
canonical product language; the docs repository must not define a competing
glossary or product contract.

User-facing product changes require a linked docs change in the release
workflow, while editorial docs improvements may publish independently.
Deterministic drift checks cover stable versions, supported commands,
canonical terms, and source links. The site does not generate its entire
narrative from repository documentation because doing so would preserve an
engineering information structure instead of translating it for DJs.
