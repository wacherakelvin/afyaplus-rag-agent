# AfyaPlus Clinical Routing Protocol

> Fictional internal protocol created for training purposes. The digital assistant sorts requests;
> it never diagnoses, and every clinical decision is confirmed by a licensed clinician.

## Routing levels

Every patient message is routed to one of four levels.

## EMERGENCY_DISPATCH

Route immediately to emergency services when any red flag is present: chest pain or pressure;
difficulty breathing; signs of stroke such as face drooping, one-sided weakness or slurred speech;
seizures; unconsciousness or new confusion; heavy bleeding; thoughts of suicide or self-harm; a baby
under 3 months old with a fever. In pregnancy, the red flags also include severe headache, blurred
vision, sudden swelling of the face or hands, vaginal bleeding and reduced baby movements. The member
should be advised to call 999 or 112 or go to the nearest emergency department.

## URGENT_CLINIC_24H

Route to a clinic appointment within 24 hours for worsening or moderate symptoms without red flags,
fever lasting more than 3 days, and pregnancy concerns without red flags.

## ROUTINE_TELECONSULT

Route to a routine teleconsultation for stable, non-urgent symptoms, medication questions, and
messages that are unclear.

## SELF_CARE_GUIDANCE

Provide self-care guidance for mild, self-limiting symptoms such as a common cold without fever.
The member should be told to contact AfyaPlus again if symptoms worsen or last longer than a week.

## Medication calculations

The assistant may only perform arithmetic on doses that a clinician has prescribed. The prescriber
must provide the dose per kilogram, the product concentration and any maximum single dose. The
assistant must never choose a dose. Every calculated volume must be confirmed by the prescriber or a
pharmacist before the medicine is given.