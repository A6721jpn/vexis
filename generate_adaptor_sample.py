
import pyfebio as feb
import os

# Create a dummy model
my_model = feb.model.Model()

# Create the adaptor from the example
adaptor = feb.meshadaptor.HexRefineAdaptor(
    elem_set="bottom-layer",
    max_iters=1,
    max_elements=10000,
    criterion=feb.meshadaptor.RelativeErrorCriterion(error=0.01, data=feb.meshadaptor.StressCriterion()),
)

# Add to model
my_model.meshadaptor_.add_adaptor(adaptor)

# Save to file
my_model.save("research_adaptive.feb")

print("Generated research_adaptive.feb")
