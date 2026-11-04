/* Test fixture only. */
#include "demo.h"

void DrawDemo(int colour, int button)
{
    DrawString(0, 10, STR_ALPHA, colour);
    DrawString(0, 20, STR_COLOUR_DARK_BLUE + colour, colour);
    GetString(STR_GOAL_QUESTION_BUTTON_CANCEL + button);
}
