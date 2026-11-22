# Nutrition recommendations (mifflin_v1)

`GET /api/v1/nutrition-goals/recommendation` reads only the authenticated account's
profile and objective. It never saves a goal. Nutrition opens this preview before
the manual editor; explicit acceptance uses the existing goal create/update API.
Existing targets remain until a successful save. Onboarding is unchanged.

Mifflin–St Jeor uses kg, cm and years: `10*w + 6.25*h - 5*age + s`, where
`s=5` for male and `s=-161` for female. This is an estimate of resting expenditure,
often called BMR in the app, not a direct measurement. Multiply by the selected
usual-activity factor: sedentary 1.20, light 1.375, moderate 1.55, high 1.725,
very high 1.90. These are approximate product defaults, not coefficients validated
by the original Mifflin paper. Include everyday movement and exercise together;
do not add recorded workout energy again. No force/cardio personalisation yet.

Starting policy: lose fat -15%; build muscle +10%; gain weight +10%; maintain 0%.
Protein: 2 g/kg for fat loss, 1.6 g/kg otherwise. Fat: 30% of target energy;
carbohydrate: remaining energy, using 4/4/9 kcal per gram. These exact percentages
are conservative Kinetix choices informed by evidence, not a universal consensus
or an optimal prescription for every individual. Weight gain does not guarantee
muscle gain. Review the weight trend, energy and training after 2–4 weeks.

Decimal arithmetic, calories rounded half-up to whole kcal, protein half-up to
0.01 g, fat and carbohydrate rounded down to 0.01 g; macro energy is at most
0.04 kcal below target. Missing inputs/objective return `available=false` with
missing fields. Automatic suggestions are restricted to adults, BMI 18.5–<40,
1200–5000 kcal and feasible macros (protein <=35% of energy). These are product
eligibility bounds, not clinical thresholds or a claim that every eligible target
is safe. Do not silently clamp or manufacture a target. Pregnancy, breastfeeding
and medically prescribed diets require individual guidance; the preview asks
users to confirm applicability before acceptance. Manual entry remains available.

## Evidence

- [Mifflin et al., 1990](https://pubmed.ncbi.nlm.nih.gov/2305711/): original resting-energy equation.
- [ISSN position stand, diets and body composition, 2017](https://pmc.ncbi.nlm.nih.gov/articles/PMC5470183/): sustained energy deficit/surplus, protein and lean-mass retention; no single best macro split.
- [Morton et al., 2018 meta-analysis](https://doi.org/10.1136/bjsports-2017-097608): resistance-training protein response around 1.6 g/kg/day, with uncertainty.
- [Iraki et al., 2019 review](https://pmc.ncbi.nlm.nih.gov/articles/PMC6680710/): 10–20% surplus and 1.6–2.2 g/kg protein for off-season bodybuilders; population-specific, not a general-population consensus.

The scope excludes paediatric and clinical diet prescriptions. Activity factors,
exact goal adjustments and eligibility bounds are versioned product policy.
