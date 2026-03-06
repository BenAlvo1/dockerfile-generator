const countVowels = (inputText) => {
    const vowels = 'aeiouAEIOU';
    return [...inputText].filter(char => vowels.includes(char)).length;
};

if (process.argv.length !== 3) {
    console.log("Usage: node vowel_counter.js '<input_text>'");
    process.exit(1);
}

const inputText = process.argv[2];
const output = countVowels(inputText);
console.log(`Vowel Count: ${output}`);
