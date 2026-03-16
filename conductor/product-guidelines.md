# GlassyTrade AI (v5) - Product Guidelines

## Prose Style & Tone
- **Professional & Technical:** Use precise financial and technical terminology (e.g., "Standard Deviation," "Auction Market Theory," "Inference").
- **Confident & Decisive:** The AI should communicate with authority based on the data it processes.
- **Concise:** Minimize fluff. Focus on high-signal information that helps in decision-making.

## Branding & Aesthetics
- **Theme:** Dark Mode by default. Primary palette: Slate-900 backgrounds, White/Gray text.
- **Accents:** Neon/Vibrant accents for signals (Green for Buy, Red for Sell, Purple for Predictions/AI).
- **Glassmorphism:** Use translucency, blurred backgrounds, and subtle borders to create a layered, modern feel.
- **Typography:** 'Inter' sans-serif for high readability in dense data environments.

## User Experience (UX) Principles
- **Data Density:** Maximize screen real estate for visualization without causing cognitive overload.
- **Real-Time Feedback:** Ensure all actions provide immediate visual or textual confirmation.
- **Seamless Flow:** The transition between charts, analysis, and management panels should be intuitive.
- **Error Handling:** Graceful handling of API failures or missing data with clear messages.

## Technical Standards
- **Component-Based:** Modular React components for each functional area.
- **Performance:** Prioritize canvas rendering for charts to maintain high frame rates.
- **Type Safety:** Strict TypeScript usage across the frontend and Pydantic for the backend.
