/* Test fixture only: a miniature CargoSpec table. */
#include "../table/strings.h"

#define MK_STR_CARGO_PLURAL(label_plural) STR_CARGO_PLURAL_ ## label_plural
#define MK_STR_CARGO_SINGULAR(label_singular) STR_CARGO_SINGULAR_ ## label_singular
#define MK_STR_QUANTITY(label_plural) STR_QUANTITY_ ## label_plural
#define MK_STR_ABBREV(label_plural) STR_ABBREV_ ## label_plural

#define MK(bt, label, colour, weight, mult, ip, td1, td2, freight, tae, str_plural, str_singular, str_volume, classes) \
    {bt, label, MK_STR_CARGO_PLURAL(str_plural), MK_STR_CARGO_SINGULAR(str_singular), \
     str_volume, MK_STR_QUANTITY(str_plural), MK_STR_ABBREV(str_plural)}

static const CargoSpec _default_cargo[] = {
    MK(1, CT_COAL, 0, 1, 1, 1, 0, 0, true, 0, COAL, COAL, STR_TONS, CargoClasses{}),
};
