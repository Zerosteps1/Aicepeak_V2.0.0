# Design

Aicepeak follows a custom design that combines two aesthetics, airy glass and paper with mostly monochrome tones, and two main colors, blue and orange.

The blue is the primary color and might be used for giving emphasis or marking something as as not negative.
The orange is the complementary and secondary color, which might be used for giving emphasis, but mostly for negative cases.

Paper is represented by filled surfaces, mostly rectangles. Some have a border as an outline for better separation.

Airy glass is represented by lightly filled, quite rounded shapes, mostly rounded rectangles that have a backdrop blur (background gets blured). 
They feature a border as an outline most of the times.

## Scaffold/root layout
The main layout is inside a top most row, like a traditional navigation bar, but split in two: the traditional navigation/menu bar and the assistant.

The assistant is a chat function that rolls up into the same hight as the navigation bar and extends to the bottom taking up the whole side if opened.

Both surfaces are airy glass surfaces.

When the assistant is opened, the main content should animate away from underneath the glass, such that it is visible that the assistant surface is infact an airy glass surface. The specifics are to be determined.

There are some elements that might not follow this animation, like colored blocks, that are set to always extend to the right screen edge.